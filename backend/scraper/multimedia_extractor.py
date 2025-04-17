import logging
import os
import json
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Dict, Any, List, Optional, Union, Tuple
import re
import shutil
import numpy as np
import whisper
import requests
from urllib.parse import urlparse, parse_qs

logger = logging.getLogger(__name__)

class MultimediaExtractor:
    """
    Extract content from multimedia sources like YouTube videos, podcasts,
    and webinars. Uses yt-dlp for downloading and Whisper for transcription.
    """
    
    def __init__(self, 
                temp_dir: Optional[str] = None,
                whisper_model: str = "base",
                keep_downloads: bool = False,
                ffmpeg_path: Optional[str] = None):
        """
        Initialize the multimedia extractor.
        
        Args:
            temp_dir: Directory for temporary files
            whisper_model: Whisper model to use (tiny, base, small, medium, large)
            keep_downloads: Whether to keep downloaded files after processing
            ffmpeg_path: Path to ffmpeg executable (if not in PATH)
        """
        self.temp_dir = temp_dir or tempfile.gettempdir()
        self.whisper_model = whisper_model
        self.keep_downloads = keep_downloads
        self.ffmpeg_path = ffmpeg_path
        
        # Ensure yt-dlp is installed
        self._check_dependencies()
        
        # Initialize Whisper model lazily
        self._model = None
    
    def _check_dependencies(self):
        """Check if required dependencies are installed."""
        try:
            subprocess.run(['yt-dlp', '--version'], 
                          stdout=subprocess.PIPE, 
                          stderr=subprocess.PIPE,
                          check=True)
            logger.info("yt-dlp is installed")
        except (subprocess.SubprocessError, FileNotFoundError):
            logger.warning("yt-dlp not found. Please install with 'pip install yt-dlp'")
        
        # Check ffmpeg
        try:
            ffmpeg_cmd = [self.ffmpeg_path] if self.ffmpeg_path else ['ffmpeg']
            subprocess.run(ffmpeg_cmd + ['-version'], 
                          stdout=subprocess.PIPE, 
                          stderr=subprocess.PIPE,
                          check=True)
            logger.info("ffmpeg is installed")
        except (subprocess.SubprocessError, FileNotFoundError):
            logger.warning("ffmpeg not found. Transcription may fail.")
    
    @property
    def model(self):
        """Lazy-load the Whisper model."""
        if self._model is None:
            try:
                logger.info(f"Loading Whisper model: {self.whisper_model}")
                self._model = whisper.load_model(self.whisper_model)
                logger.info("Whisper model loaded successfully")
            except Exception as e:
                logger.error(f"Error loading Whisper model: {str(e)}")
                raise
        return self._model
    
    def extract_from_youtube(self, url: str, include_comments: bool = False) -> Dict[str, Any]:
        """
        Extract content from a YouTube video.
        
        Args:
            url: YouTube URL
            include_comments: Whether to include video comments
            
        Returns:
            dict: Extracted content
        """
        try:
            logger.info(f"Extracting content from YouTube: {url}")
            
            # Extract video ID
            video_id = self._extract_youtube_id(url)
            if not video_id:
                raise ValueError(f"Could not extract YouTube video ID from URL: {url}")
            
            # Create temp directory for this video
            temp_path = os.path.join(self.temp_dir, f"webintel_yt_{video_id}")
            os.makedirs(temp_path, exist_ok=True)
            
            # Get video info using yt-dlp
            video_info = self._get_youtube_info(url)
            
            result = {
                'video_id': video_id,
                'title': video_info.get('title', ''),
                'description': video_info.get('description', ''),
                'upload_date': video_info.get('upload_date', ''),
                'channel': video_info.get('channel', ''),
                'channel_id': video_info.get('channel_id', ''),
                'duration': video_info.get('duration', 0),
                'view_count': video_info.get('view_count', 0),
                'like_count': video_info.get('like_count', 0),
                'categories': video_info.get('categories', []),
                'tags': video_info.get('tags', []),
                'thumbnail': video_info.get('thumbnail', ''),
                'subtitles': {}
            }
            
            # Check for available subtitles first
            subtitles = video_info.get('subtitles', {})
            if subtitles and 'en' in subtitles:
                logger.info(f"Found existing English subtitles for {video_id}")
                # Download subtitles
                subtitle_path = os.path.join(temp_path, f"{video_id}.en.vtt")
                subtitle_cmd = [
                    'yt-dlp',
                    '--write-sub',
                    '--skip-download',
                    '--sub-lang', 'en',
                    '--convert-subs', 'vtt',
                    '-o', os.path.join(temp_path, f"{video_id}"),
                    url
                ]
                subprocess.run(subtitle_cmd, check=True)
                
                if os.path.exists(subtitle_path):
                    # Parse VTT file
                    subtitles_text = self._parse_vtt(subtitle_path)
                    result['subtitles']['en'] = subtitles_text
                    result['transcript'] = ' '.join([s['text'] for s in subtitles_text])
            else:
                # No subtitles available, download audio and transcribe
                logger.info(f"No existing subtitles, downloading audio for {video_id}")
                audio_path = os.path.join(temp_path, f"{video_id}.mp3")
                
                # Download audio only
                download_cmd = [
                    'yt-dlp',
                    '-f', 'bestaudio',
                    '-x',
                    '--audio-format', 'mp3',
                    '-o', audio_path,
                    url
                ]
                subprocess.run(download_cmd, check=True)
                
                if os.path.exists(audio_path):
                    # Transcribe with Whisper
                    logger.info(f"Transcribing audio for {video_id}")
                    transcript = self._transcribe_audio(audio_path)
                    result['transcript'] = transcript['text']
                    result['subtitles']['whisper'] = transcript['segments']
                else:
                    logger.warning(f"Failed to download audio for {video_id}")
            
            # Get comments if requested
            if include_comments:
                logger.info(f"Fetching comments for {video_id}")
                comments = self._get_youtube_comments(url)
                result['comments'] = comments[:100]  # Limit to 100 comments
            
            # Extract marketing-specific information
            result.update(self._extract_lecture_info(result))
            
            # Clean up temp files if not keeping them
            if not self.keep_downloads:
                try:
                    shutil.rmtree(temp_path)
                    logger.info(f"Cleaned up temporary files for {video_id}")
                except Exception as e:
                    logger.warning(f"Error cleaning up temporary files: {str(e)}")
            
            return result
            
        except Exception as e:
            logger.error(f"Error extracting content from YouTube {url}: {str(e)}")
            return {
                'error': str(e),
                'url': url
            }
    
    def extract_from_podcast(self, url: str) -> Dict[str, Any]:
        """
        Extract content from a podcast episode.
        
        Args:
            url: Podcast URL (direct mp3 or hosting platform)
            
        Returns:
            dict: Extracted content
        """
        try:
            logger.info(f"Extracting content from podcast: {url}")
            
            # Generate a unique ID for this podcast
            podcast_id = self._generate_podcast_id(url)
            
            # Create temp directory for this podcast
            temp_path = os.path.join(self.temp_dir, f"webintel_podcast_{podcast_id}")
            os.makedirs(temp_path, exist_ok=True)
            
            # Download the audio file
            audio_path = os.path.join(temp_path, f"{podcast_id}.mp3")
            
            # Check if it's a direct audio file or a hosting platform
            if url.lower().endswith(('.mp3', '.m4a', '.wav')):
                # Direct download
                response = requests.get(url, stream=True)
                with open(audio_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
            else:
                # Use yt-dlp to extract from hosting platforms
                download_cmd = [
                    'yt-dlp',
                    '-f', 'bestaudio',
                    '-x',
                    '--audio-format', 'mp3',
                    '-o', audio_path,
                    url
                ]
                subprocess.run(download_cmd, check=True)
            
            # Initialize result with basic info
            result = {
                'podcast_id': podcast_id,
                'url': url,
            }
            
            # Try to get metadata
            try:
                info_cmd = [
                    'yt-dlp',
                    '-j',
                    url
                ]
                info_output = subprocess.run(info_cmd, capture_output=True, text=True, check=True).stdout
                info = json.loads(info_output)
                
                result.update({
                    'title': info.get('title', ''),
                    'description': info.get('description', ''),
                    'upload_date': info.get('upload_date', ''),
                    'duration': info.get('duration', 0),
                    'uploader': info.get('uploader', ''),
                })
            except Exception as e:
                logger.warning(f"Could not extract podcast metadata: {str(e)}")
            
            # Transcribe the audio
            if os.path.exists(audio_path):
                logger.info(f"Transcribing podcast {podcast_id}")
                transcript = self._transcribe_audio(audio_path)
                result['transcript'] = transcript['text']
                result['segments'] = transcript['segments']
            else:
                logger.warning(f"Failed to download podcast audio for {podcast_id}")
            
            # Extract marketing-specific information
            result.update(self._extract_podcast_info(result))
            
            # Clean up temp files if not keeping them
            if not self.keep_downloads:
                try:
                    shutil.rmtree(temp_path)
                    logger.info(f"Cleaned up temporary files for {podcast_id}")
                except Exception as e:
                    logger.warning(f"Error cleaning up temporary files: {str(e)}")
            
            return result
            
        except Exception as e:
            logger.error(f"Error extracting content from podcast {url}: {str(e)}")
            return {
                'error': str(e),
                'url': url
            }
    
    def extract_from_webinar(self, url: str) -> Dict[str, Any]:
        """
        Extract content from a webinar recording.
        Similar to YouTube but can handle other platforms like Vimeo, Wistia, etc.
        
        Args:
            url: Webinar URL
            
        Returns:
            dict: Extracted content
        """
        try:
            logger.info(f"Extracting content from webinar: {url}")
            
            # Generate a unique ID for this webinar
            webinar_id = self._generate_webinar_id(url)
            
            # Create temp directory for this webinar
            temp_path = os.path.join(self.temp_dir, f"webintel_webinar_{webinar_id}")
            os.makedirs(temp_path, exist_ok=True)
            
            # Get video info using yt-dlp
            try:
                info_cmd = [
                    'yt-dlp',
                    '-j',
                    url
                ]
                info_output = subprocess.run(info_cmd, capture_output=True, text=True, check=True).stdout
                video_info = json.loads(info_output)
            except Exception as e:
                logger.warning(f"Could not extract webinar metadata: {str(e)}")
                video_info = {}
            
            result = {
                'webinar_id': webinar_id,
                'url': url,
                'title': video_info.get('title', ''),
                'description': video_info.get('description', ''),
                'upload_date': video_info.get('upload_date', ''),
                'duration': video_info.get('duration', 0),
                'uploader': video_info.get('uploader', ''),
                'view_count': video_info.get('view_count', 0),
                'thumbnail': video_info.get('thumbnail', ''),
            }
            
            # Download audio for transcription
            audio_path = os.path.join(temp_path, f"{webinar_id}.mp3")
            download_cmd = [
                'yt-dlp',
                '-f', 'bestaudio',
                '-x',
                '--audio-format', 'mp3',
                '-o', audio_path,
                url
            ]
            subprocess.run(download_cmd, check=True)
            
            # Transcribe the audio
            if os.path.exists(audio_path):
                logger.info(f"Transcribing webinar {webinar_id}")
                transcript = self._transcribe_audio(audio_path)
                result['transcript'] = transcript['text']
                result['segments'] = transcript['segments']
            else:
                logger.warning(f"Failed to download webinar audio for {webinar_id}")
            
            # Extract marketing-specific information
            result.update(self._extract_webinar_info(result))
            
            # Clean up temp files if not keeping them
            if not self.keep_downloads:
                try:
                    shutil.rmtree(temp_path)
                    logger.info(f"Cleaned up temporary files for {webinar_id}")
                except Exception as e:
                    logger.warning(f"Error cleaning up temporary files: {str(e)}")
            
            return result
            
        except Exception as e:
            logger.error(f"Error extracting content from webinar {url}: {str(e)}")
            return {
                'error': str(e),
                'url': url
            }
    
    def _transcribe_audio(self, audio_path: str) -> Dict[str, Any]:
        """
        Transcribe audio file using Whisper.
        
        Args:
            audio_path: Path to audio file
            
        Returns:
            dict: Transcription results
        """
        try:
            logger.info(f"Transcribing audio: {audio_path}")
            start_time = time.time()
            
            # Load model if needed
            model = self.model
            
            # Transcribe
            result = model.transcribe(audio_path)
            
            end_time = time.time()
            duration = end_time - start_time
            logger.info(f"Transcription completed in {duration:.2f} seconds")
            
            return result
        except Exception as e:
            logger.error(f"Error transcribing audio: {str(e)}")
            return {'text': '', 'segments': []}
    
    def _extract_youtube_id(self, url: str) -> str:
        """
        Extract YouTube video ID from URL.
        
        Args:
            url: YouTube URL
            
        Returns:
            str: Video ID
        """
        patterns = [
            # youtu.be URLs
            r'youtu\.be\/([^\/\?]+)',
            # Standard YouTube URL with v parameter
            r'youtube\.com\/watch\?v=([^&]+)',
            # YouTube embedded URLs
            r'youtube\.com\/embed\/([^\/\?]+)',
            # YouTube shorts
            r'youtube\.com\/shorts\/([^\/\?]+)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        
        # If patterns fail, try parsing URL
        parsed_url = urlparse(url)
        if 'youtube.com' in parsed_url.netloc:
            query_params = parse_qs(parsed_url.query)
            if 'v' in query_params:
                return query_params['v'][0]
        
        return ''
    
    def _get_youtube_info(self, url: str) -> Dict[str, Any]:
        """
        Get metadata about a YouTube video.
        
        Args:
            url: YouTube URL
            
        Returns:
            dict: Video metadata
        """
        try:
            command = [
                'yt-dlp',
                '-j',
                url
            ]
            result = subprocess.run(command, capture_output=True, text=True, check=True)
            return json.loads(result.stdout)
        except Exception as e:
            logger.error(f"Error getting YouTube info: {str(e)}")
            return {}
    
    def _get_youtube_comments(self, url: str, max_comments: int = 100) -> List[Dict[str, Any]]:
        """
        Get comments from a YouTube video.
        
        Args:
            url: YouTube URL
            max_comments: Maximum number of comments to retrieve
            
        Returns:
            list: Video comments
        """
        try:
            # Use yt-dlp to extract comments
            command = [
                'yt-dlp',
                '--skip-download',
                '--get-comments',
                '--max-comments', str(max_comments),
                url
            ]
            result = subprocess.run(command, capture_output=True, text=True, check=True)
            
            # Parse comments (format depends on yt-dlp version)
            comments_raw = result.stdout.strip().split('\n')
            comments = []
            
            for line in comments_raw:
                try:
                    comment = json.loads(line)
                    comments.append(comment)
                except:
                    # Fallback for older versions that don't output JSON
                    if line and not line.startswith('{'):
                        comments.append({'text': line})
            
            return comments
        except Exception as e:
            logger.error(f"Error getting YouTube comments: {str(e)}")
            return []
    
    def _parse_vtt(self, vtt_path: str) -> List[Dict[str, Any]]:
        """
        Parse a VTT subtitle file.
        
        Args:
            vtt_path: Path to VTT file
            
        Returns:
            list: List of subtitle segments
        """
        try:
            with open(vtt_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            segments = []
            pattern = r'(\d{2}:\d{2}:\d{2}\.\d{3}) --> (\d{2}:\d{2}:\d{2}\.\d{3})[^\n]*\n((?:.+\n)+)'
            
            for match in re.finditer(pattern, content):
                start, end, text_lines = match.groups()
                text = ' '.join([line.strip() for line in text_lines.strip().split('\n')])
                
                segments.append({
                    'start': start,
                    'end': end,
                    'text': text
                })
            
            return segments
        except Exception as e:
            logger.error(f"Error parsing VTT file: {str(e)}")
            return []
    
    def _generate_podcast_id(self, url: str) -> str:
        """
        Generate a unique ID for a podcast.
        
        Args:
            url: Podcast URL
            
        Returns:
            str: Unique ID
        """
        return f"pod_{hash(url) % 10000000:07d}"
    
    def _generate_webinar_id(self, url: str) -> str:
        """
        Generate a unique ID for a webinar.
        
        Args:
            url: Webinar URL
            
        Returns:
            str: Unique ID
        """
        return f"web_{hash(url) % 10000000:07d}"
    
    def _extract_lecture_info(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract marketing lecture specific information.
        
        Args:
            data: Video data
            
        Returns:
            dict: Lecture-specific information
        """
        result = {'type': 'lecture'}
        
        # Check if it's likely a marketing lecture
        title = data.get('title', '').lower()
        description = data.get('description', '').lower()
        transcript = data.get('transcript', '').lower()
        
        marketing_terms = ['marketing', 'digital marketing', 'content marketing', 'seo', 
                         'social media', 'advertising', 'brand', 'strategy']
        
        # Check if title or description contains marketing terms
        is_marketing = any(term in title for term in marketing_terms) or \
                     any(term in description[:500] for term in marketing_terms)
        
        result['is_marketing_content'] = is_marketing
        
        # Extract topics
        topics = []
        topic_patterns = [
            r'this lecture covers ([\w\s,]+)',
            r'topic[s]?:? ([\w\s,]+)',
            r'today we\'ll discuss ([\w\s,]+)',
            r'(?:in|this) this video,? (?:we|i) (?:will|\'ll) (?:talk about|discuss|cover) ([\w\s,]+)'
        ]
        
        for pattern in topic_patterns:
            matches = re.findall(pattern, description.lower())
            topics.extend(matches)
        
        if not topics and transcript:
            # Try to find topics in the first 1000 characters of the transcript
            for pattern in topic_patterns:
                matches = re.findall(pattern, transcript[:1000].lower())
                topics.extend(matches)
        
        result['topics'] = [topic.strip() for topic in topics if len(topic.strip()) > 3] if topics else []
        
        # Try to determine if it's part of a course
        course_patterns = [
            r'lecture (\d+)',
            r'part (\d+)',
            r'session (\d+)',
            r'module (\d+)'
        ]
        
        for pattern in course_patterns:
            match = re.search(pattern, title.lower())
            if match:
                result['lecture_number'] = match.group(1)
                break
        
        # Try to extract course name
        course_name_patterns = [
            r'(.+?):?\s+lecture \d+',
            r'(.+?):?\s+part \d+',
            r'(.+?):?\s+session \d+',
            r'(.+?):?\s+module \d+'
        ]
        
        for pattern in course_name_patterns:
            match = re.search(pattern, title.lower())
            if match:
                result['course_name'] = match.group(1).strip().title()
                break
        
        return result
    
    def _extract_podcast_info(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract marketing podcast specific information.
        
        Args:
            data: Podcast data
            
        Returns:
            dict: Podcast-specific information
        """
        result = {'type': 'podcast'}
        
        # Check if it's likely a marketing podcast
        title = data.get('title', '').lower()
        description = data.get('description', '').lower()
        transcript = data.get('transcript', '').lower()
        
        marketing_terms = ['marketing', 'digital marketing', 'content marketing', 'seo', 
                         'social media', 'advertising', 'brand', 'strategy']
        
        # Check if title or description contains marketing terms
        is_marketing = any(term in title for term in marketing_terms) or \
                     any(term in description[:500] for term in marketing_terms)
        
        result['is_marketing_content'] = is_marketing
        
        # Try to extract episode number
        episode_patterns = [
            r'episode (\d+)',
            r'ep\.? (\d+)',
            r'e(\d+)'
        ]
        
        for pattern in episode_patterns:
            match = re.search(pattern, title.lower())
            if match:
                result['episode_number'] = match.group(1)
                break
        
        # Try to extract podcast name
        podcast_name_patterns = [
            r'(.+?):?\s+episode \d+',
            r'(.+?):?\s+ep\.? \d+',
            r'(.+?):?\s+e\d+'
        ]
        
        for pattern in podcast_name_patterns:
            match = re.search(pattern, title.lower())
            if match:
                result['podcast_name'] = match.group(1).strip().title()
                break
        
        # Try to extract guest information
        guest_patterns = [
            r'(?:with|featuring|guest) (.+?)(?:\s+on\s+|\s+-\s+|$)',
            r'interview with (.+?)(?:\s+on\s+|\s+-\s+|$)'
        ]
        
        for pattern in guest_patterns:
            match = re.search(pattern, title.lower())
            if match:
                result['guest'] = match.group(1).strip().title()
                break
        
        return result
    
    def _extract_webinar_info(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract marketing webinar specific information.
        
        Args:
            data: Webinar data
            
        Returns:
            dict: Webinar-specific information
        """
        result = {'type': 'webinar'}
        
        # Check if it's likely a marketing webinar
        title = data.get('title', '').lower()
        description = data.get('description', '').lower()
        transcript = data.get('transcript', '').lower()
        
        marketing_terms = ['marketing', 'digital marketing', 'content marketing', 'seo', 
                         'social media', 'advertising', 'brand', 'strategy']
        
        # Check if title or description contains marketing terms
        is_marketing = any(term in title for term in marketing_terms) or \
                     any(term in description[:500] for term in marketing_terms)
        
        result['is_marketing_content'] = is_marketing
        
        # Try to extract host/speaker information
        host_patterns = [
            r'(?:hosted by|presented by|with) (.+?)(?:\s+on\s+|\s+-\s+|$)',
            r'speaker:? (.+?)(?:\s+on\s+|\s+-\s+|$)'
        ]
        
        for pattern in host_patterns:
            match = re.search(pattern, description.lower())
            if match:
                result['host'] = match.group(1).strip().title()
                break
        
        # Try to detect if it's a product demo
        demo_indicators = ['demo', 'demonstration', 'walkthrough', 'tutorial', 'how to use', 'how to setup']
        is_demo = any(indicator in title.lower() or indicator in description.lower() for indicator in demo_indicators)
        
        if is_demo:
            result['webinar_type'] = 'product_demo'
        elif 'case study' in title.lower() or 'case study' in description.lower():
            result['webinar_type'] = 'case_study'
        elif 'panel' in title.lower() or 'panel' in description.lower():
            result['webinar_type'] = 'panel_discussion'
        else:
            result['webinar_type'] = 'presentation'
        
        return result

# Convenience functions
def extract_youtube_lecture(url: str) -> Dict[str, Any]:
    """
    Extract content from a YouTube lecture.
    
    Args:
        url: YouTube URL
        
    Returns:
        dict: Extracted lecture content
    """
    extractor = MultimediaExtractor()
    return extractor.extract_from_youtube(url)

def extract_marketing_podcast(url: str) -> Dict[str, Any]:
    """
    Extract content from a marketing podcast.
    
    Args:
        url: Podcast URL
        
    Returns:
        dict: Extracted podcast content
    """
    extractor = MultimediaExtractor()
    return extractor.extract_from_podcast(url)

def extract_marketing_webinar(url: str) -> Dict[str, Any]:
    """
    Extract content from a marketing webinar.
    
    Args:
        url: Webinar URL
        
    Returns:
        dict: Extracted webinar content
    """
    extractor = MultimediaExtractor()
    return extractor.extract_from_webinar(url)