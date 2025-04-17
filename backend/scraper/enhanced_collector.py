import logging
import os
import json
import time
from typing import Dict, Any, List, Optional, Union, Callable
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

from .base_scraper import BaseScraper, get_page_content
from .pdf_extractor import PDFExtractor, extract_pdf
from .social_media import TwitterScraper, search_marketing_tweets
from .multimedia_extractor import MultimediaExtractor, extract_youtube_lecture, extract_marketing_podcast
from .dataset_collector import DatasetCollector, get_marketing_datasets
from .metadata import extract_metadata, extract_structured_data
from .domain_analyzers import get_domain_analyzer, detect_content_domain

logger = logging.getLogger(__name__)

class EnhancedContentCollector:
    """
    Unified handler for collecting various types of content from multiple sources.
    Integrates web scraping, PDF extraction, social media, multimedia, and datasets
    with optional domain-specific analysis.
    """
    
    def __init__(self, 
                max_workers: int = 5,
                temp_dir: Optional[str] = None,
                keep_downloads: bool = False,
                domain_expertise: Optional[str] = None):
        """
        Initialize the enhanced content collector.
        
        Args:
            max_workers: Maximum number of concurrent workers
            temp_dir: Directory for temporary files
            keep_downloads: Whether to keep downloaded files
            domain_expertise: Optional domain expertise for specialized analysis
                             (e.g., "marketing", "legal", "academic", etc.)
        """
        self.max_workers = max_workers
        self.temp_dir = temp_dir
        self.keep_downloads = keep_downloads
        self.domain_expertise = domain_expertise
        
        # Initialize components
        self.scraper = BaseScraper(headless=True)
        self.pdf_extractor = PDFExtractor(temp_dir=temp_dir)
        self.tweet_scraper = TwitterScraper()
        self.multimedia_extractor = MultimediaExtractor(temp_dir=temp_dir, keep_downloads=keep_downloads)
        self.dataset_collector = DatasetCollector(output_dir=temp_dir)
        
        # Initialize domain analyzer
        self.domain_analyzer = get_domain_analyzer(domain_expertise)
        
        logger.info(f"Initialized EnhancedContentCollector with domain expertise: {domain_expertise or 'general'}")
    
    def collect_content(self, 
                       query: str,
                       sources: List[str] = None,
                       max_items_per_source: int = 5,
                       callback: Optional[Callable] = None) -> Dict[str, List[Dict[str, Any]]]:
        """
        Collect content from multiple sources based on a query.
        
        Args:
            query: Search query
            sources: List of sources to collect from ('web', 'pdf', 'social', 'video', 'podcast', 'dataset')
            max_items_per_source: Maximum items to collect per source
            callback: Optional callback function to process each item
            
        Returns:
            dict: Collected data grouped by source
        """
        if sources is None:
            sources = ['web', 'pdf', 'social', 'video', 'podcast', 'dataset']
        
        logger.info(f"Collecting content for query: {query} from sources: {sources}")
        
        results = {source: [] for source in sources}
        
        # Use ThreadPoolExecutor for parallelism
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Web scraping
            if 'web' in sources:
                logger.info("Collecting web content")
                web_futures = []
                
                # First get search results
                search_results = self._get_search_results(query, max_results=max_items_per_source)
                
                for result in search_results:
                    future = executor.submit(self._process_web_page, result['url'], result)
                    web_futures.append(future)
                
                # Process completed futures
                for future in web_futures:
                    try:
                        result = future.result()
                        if result:
                            # Apply domain-specific analysis if needed
                            if self.domain_expertise:
                                result.update(self.domain_analyzer.analyze_web_content(result))
                            
                            results['web'].append(result)
                            if callback:
                                callback('web', result)
                    except Exception as e:
                        logger.error(f"Error processing web future: {str(e)}")
            
            # PDF extraction
            if 'pdf' in sources:
                logger.info("Collecting PDF content")
                pdf_futures = []
                
                # Get PDF URLs for the query
                pdf_urls = self._get_pdf_urls(query, max_results=max_items_per_source)
                
                for url in pdf_urls:
                    future = executor.submit(self._process_pdf, url)
                    pdf_futures.append(future)
                
                # Process completed futures
                for future in pdf_futures:
                    try:
                        result = future.result()
                        if result:
                            # Apply domain-specific analysis if needed
                            if self.domain_expertise:
                                result.update(self.domain_analyzer.analyze_pdf_content(result))
                                
                            results['pdf'].append(result)
                            if callback:
                                callback('pdf', result)
                    except Exception as e:
                        logger.error(f"Error processing PDF future: {str(e)}")
            
            # Social media
            if 'social' in sources:
                logger.info("Collecting social media content")
                social_futures = []
                
                # Get tweets
                search_terms = f"{query}"
                if self.domain_expertise:
                    search_terms += f" {self.domain_expertise}"
                    
                future = executor.submit(self._search_social_content, search_terms, max_results=max_items_per_source)
                social_futures.append(('twitter', future))
                
                # Process completed futures
                for source_type, future in social_futures:
                    try:
                        items = future.result()
                        if items:
                            for item in items:
                                item['source_type'] = source_type
                                
                                # Apply domain-specific analysis if needed
                                if self.domain_expertise:
                                    item.update(self.domain_analyzer.analyze_social_content(item))
                                    
                                results['social'].append(item)
                                if callback:
                                    callback('social', item)
                    except Exception as e:
                        logger.error(f"Error processing social future: {str(e)}")
            
            # Video content
            if 'video' in sources:
                logger.info("Collecting video content")
                video_futures = []
                
                # Get videos related to query
                video_urls = self._get_video_urls(query, max_results=max_items_per_source)
                
                for url in video_urls:
                    future = executor.submit(self._process_video, url)
                    video_futures.append(future)
                
                # Process completed futures
                for future in video_futures:
                    try:
                        result = future.result()
                        if result and 'error' not in result:
                            # Apply domain-specific analysis if needed
                            if self.domain_expertise:
                                result.update(self.domain_analyzer.analyze_video_content(result))
                                
                            results['video'].append(result)
                            if callback:
                                callback('video', result)
                    except Exception as e:
                        logger.error(f"Error processing video future: {str(e)}")
            
            # Podcast content
            if 'podcast' in sources:
                logger.info("Collecting podcast content")
                podcast_futures = []
                
                # Get podcasts related to query
                podcast_urls = self._get_podcast_urls(query, max_results=max_items_per_source)
                
                for url in podcast_urls:
                    future = executor.submit(self._process_podcast, url)
                    podcast_futures.append(future)
                
                # Process completed futures
                for future in podcast_futures:
                    try:
                        result = future.result()
                        if result and 'error' not in result:
                            # Apply domain-specific analysis if needed
                            if self.domain_expertise:
                                result.update(self.domain_analyzer.analyze_podcast_content(result))
                                
                            results['podcast'].append(result)
                            if callback:
                                callback('podcast', result)
                    except Exception as e:
                        logger.error(f"Error processing podcast future: {str(e)}")
            
            # Dataset content
            if 'dataset' in sources:
                logger.info("Collecting dataset content")
                
                try:
                    # This is synchronous since it's a quick API call
                    dataset_query = query
                    if self.domain_expertise:
                        dataset_query = f"{query} {self.domain_expertise}"
                        
                    datasets = self._search_datasets(dataset_query)
                    datasets = datasets[:max_items_per_source]
                    
                    # Apply domain-specific analysis if needed
                    if self.domain_expertise:
                        for dataset in datasets:
                            dataset.update(self.domain_analyzer.analyze_dataset_content(dataset))
                            
                    results['dataset'] = datasets
                    
                    if callback:
                        for dataset in results['dataset']:
                            callback('dataset', dataset)
                except Exception as e:
                    logger.error(f"Error collecting datasets: {str(e)}")
        
        # Log summary
        for source, items in results.items():
            logger.info(f"Collected {len(items)} items from {source}")
        
        return results
    
    def process_url(self, url: str) -> Dict[str, Any]:
        """
        Process a URL by detecting its type and using the appropriate extractor.
        
        Args:
            url: URL to process
            
        Returns:
            dict: Extracted content
        """
        # Determine URL type
        if url.lower().endswith('.pdf'):
            result = self._process_pdf(url)
        elif 'youtube.com' in url or 'youtu.be' in url:
            result = self._process_video(url)
        elif url.lower().endswith(('.mp3', '.m4a', '.wav')) or any(domain in url for domain in ['anchor.fm', 'podcasts.apple.com', 'spotify.com/episode']):
            result = self._process_podcast(url)
        elif any(domain in url for domain in ['twitter.com', 'x.com']):
            result = self._process_tweet(url)
        else:
            # Default to web page
            result = self._process_web_page(url)
        
        # Apply domain-specific analysis if configured
        if self.domain_expertise and result:
            # Determine content type
            content_type = self._determine_content_type(url, result)
            
            # Apply appropriate analyzer
            if content_type == 'web_page':
                result.update(self.domain_analyzer.analyze_web_content(result))
            elif content_type == 'pdf':
                result.update(self.domain_analyzer.analyze_pdf_content(result))
            elif content_type == 'video':
                result.update(self.domain_analyzer.analyze_video_content(result))
            elif content_type == 'podcast':
                result.update(self.domain_analyzer.analyze_podcast_content(result))
            elif content_type == 'social':
                result.update(self.domain_analyzer.analyze_social_content(result))
        
        return result
    
    def download_dataset(self, dataset_info: Dict[str, Any]) -> Dict[str, Any]:
        """
        Download and process a dataset.
        
        Args:
            dataset_info: Dataset metadata
            
        Returns:
            dict: Dataset content and metadata
        """
        try:
            dataframes = self.dataset_collector.load_dataset_from_info(dataset_info)
            
            # Prepare result
            result = {
                'dataset_info': dataset_info,
                'files': [],
                'summary': {}
            }
            
            # Process each dataframe
            for filename, df in dataframes.items():
                file_info = {
                    'filename': filename,
                    'rows': len(df),
                    'columns': list(df.columns),
                    'preview': df.head(5).to_dict(orient='records')
                }
                
                # Add basic statistics
                try:
                    file_info['stats'] = df.describe().to_dict()
                except Exception:
                    # Some columns might not be numeric
                    pass
                
                result['files'].append(file_info)
            
            # Generate summary
            if dataframes:
                result['summary'] = {
                    'total_files': len(dataframes),
                    'total_rows': sum(len(df) for df in dataframes.values()),
                    'file_names': list(dataframes.keys())
                }
            
            # Apply domain-specific analysis if needed
            if self.domain_expertise:
                result.update(self.domain_analyzer.analyze_dataset_content(result))
            
            return result
            
        except Exception as e:
            logger.error(f"Error downloading dataset: {str(e)}")
            return {
                'dataset_info': dataset_info,
                'error': str(e)
            }
    
    def _get_search_results(self, query: str, max_results: int = 10) -> List[Dict[str, Any]]:
        """
        Get web search results for a query.
        
        Args:
            query: Search query
            max_results: Maximum number of results
            
        Returns:
            list: Search results
        """
        try:
            from ..search.bing import search_bing
            
            # Add domain expertise to query if specified
            search_query = query
            if self.domain_expertise:
                search_query = f"{query} {self.domain_expertise}"
                
            # Use existing Bing search from WebIntel
            results = search_bing(search_query, num_results=max_results)
            
            # Add timestamp
            for result in results:
                result['timestamp'] = time.time()
            
            return results
        except Exception as e:
            logger.error(f"Error getting search results: {str(e)}")
            return []
    
    def _process_web_page(self, url: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Process a web page.
        
        Args:
            url: URL to process
            metadata: Optional metadata about the page
            
        Returns:
            dict: Processed content
        """
        try:
            logger.info(f"Processing web page: {url}")
            
            # Get page content
            html, scrape_metadata = self.scraper.get_page_content(url)
            
            if not html:
                logger.warning(f"Failed to get content from {url}")
                return {}
            
            # Extract metadata and content
            content_metadata = extract_metadata(url, html)
            
            # Extract structured data
            structured_data = extract_structured_data(html, url)
            
            # Combine all metadata
            result = {
                'url': url,
                'content_type': 'web_page',
                'title': content_metadata.get('title') or scrape_metadata.get('title', ''),
                'text': content_metadata.get('text', ''),
                'authors': content_metadata.get('authors', []),
                'published_date': content_metadata.get('published_date'),
                'structured_data': structured_data,
                'timestamp': time.time(),
                'html': html  # Include HTML for domain-specific analysis
            }
            
            # Add original metadata if provided
            if metadata:
                result['search_metadata'] = metadata
            
            # Detect content domain if not specified
            if not self.domain_expertise:
                detected_domain = detect_content_domain(result['text'], content_metadata)
                if detected_domain != 'general':
                    result['detected_domain'] = detected_domain
                    # Dynamically apply domain analysis
                    temp_analyzer = get_domain_analyzer(detected_domain)
                    domain_data = temp_analyzer.analyze_web_content(result)
                    result.update(domain_data)
            
            return result
            
        except Exception as e:
            logger.error(f"Error processing web page {url}: {str(e)}")
            return {
                'url': url,
                'content_type': 'web_page',
                'error': str(e),
                'timestamp': time.time()
            }
    
    def _process_pdf(self, url: str) -> Dict[str, Any]:
        """
        Process a PDF file.
        
        Args:
            url: URL to PDF
            
        Returns:
            dict: Extracted content
        """
        try:
            logger.info(f"Processing PDF: {url}")
            
            # Extract PDF content
            pdf_data = extract_pdf(url)
            
            if not pdf_data or not pdf_data.get('text'):
                logger.warning(f"Failed to extract content from PDF {url}")
                return {}
            
            # Prepare result
            result = {
                'url': url,
                'content_type': 'pdf',
                'title': pdf_data.get('metadata', {}).get('title', 'Untitled PDF'),
                'text': pdf_data.get('text', ''),
                'author': pdf_data.get('metadata', {}).get('author', ''),
                'pages': len(pdf_data.get('pages', [])),
                'tables': pdf_data.get('tables', []),
                'timestamp': time.time()
            }
            
            # Detect content domain if not specified
            if not self.domain_expertise:
                detected_domain = detect_content_domain(result['text'], pdf_data.get('metadata', {}))
                if detected_domain != 'general':
                    result['detected_domain'] = detected_domain
                    # Dynamically apply domain analysis
                    temp_analyzer = get_domain_analyzer(detected_domain)
                    domain_data = temp_analyzer.analyze_pdf_content(result)
                    result.update(domain_data)
            
            return result
            
        except Exception as e:
            logger.error(f"Error processing PDF {url}: {str(e)}")
            return {
                'url': url,
                'content_type': 'pdf',
                'error': str(e),
                'timestamp': time.time()
            }
    
    def _process_video(self, url: str) -> Dict[str, Any]:
        """
        Process a video.
        
        Args:
            url: Video URL
            
        Returns:
            dict: Extracted content
        """
        try:
            logger.info(f"Processing video: {url}")
            
            # Use multimedia extractor
            result = self.multimedia_extractor.extract_from_youtube(url)
            
            # Ensure content type
            result['content_type'] = 'video'
            
            # Detect content domain if not specified
            if not self.domain_expertise and 'transcript' in result:
                detected_domain = detect_content_domain(result['transcript'], 
                                                      {'title': result.get('title', ''),
                                                       'description': result.get('description', '')})
                if detected_domain != 'general':
                    result['detected_domain'] = detected_domain
                    # Dynamically apply domain analysis
                    temp_analyzer = get_domain_analyzer(detected_domain)
                    domain_data = temp_analyzer.analyze_video_content(result)
                    result.update(domain_data)
            
            return result
            
        except Exception as e:
            logger.error(f"Error processing video {url}: {str(e)}")
            return {
                'url': url,
                'content_type': 'video',
                'error': str(e),
                'timestamp': time.time()
            }
    
    def _process_podcast(self, url: str) -> Dict[str, Any]:
        """
        Process a podcast.
        
        Args:
            url: Podcast URL
            
        Returns:
            dict: Extracted content
        """
        try:
            logger.info(f"Processing podcast: {url}")
            
            # Use multimedia extractor
            result = self.multimedia_extractor.extract_from_podcast(url)
            
            # Ensure content type
            result['content_type'] = 'podcast'
            
            # Detect content domain if not specified
            if not self.domain_expertise and 'transcript' in result:
                detected_domain = detect_content_domain(result['transcript'], 
                                                      {'title': result.get('title', ''),
                                                       'description': result.get('description', '')})
                if detected_domain != 'general':
                    result['detected_domain'] = detected_domain
                    # Dynamically apply domain analysis
                    temp_analyzer = get_domain_analyzer(detected_domain)
                    domain_data = temp_analyzer.analyze_podcast_content(result)
                    result.update(domain_data)
            
            return result
            
        except Exception as e:
            logger.error(f"Error processing podcast {url}: {str(e)}")
            return {
                'url': url,
                'content_type': 'podcast',
                'error': str(e),
                'timestamp': time.time()
            }
    
    def _process_tweet(self, url: str) -> Dict[str, Any]:
        """
        Process a tweet or Twitter thread.
        
        Args:
            url: Tweet URL
            
        Returns:
            dict: Extracted content
        """
        try:
            logger.info(f"Processing tweet: {url}")
            
            # Extract tweet ID from URL
            tweet_id = self._extract_tweet_id(url)
            
            if not tweet_id:
                logger.warning(f"Could not extract tweet ID from {url}")
                return {}
            
            # Get tweet thread
            thread = self.tweet_scraper.get_thread(tweet_id)
            
            if not thread:
                logger.warning(f"Could not retrieve thread for {url}")
                return {}
            
            # Combine thread text
            text = "\n\n".join([tweet.get('text', '') for tweet in thread])
            
            # Prepare result
            result = {
                'url': url,
                'content_type': 'social',
                'social_platform': 'twitter',
                'tweet_id': tweet_id,
                'text': text,
                'thread': thread,
                'author': thread[0].get('author') if thread else None,
                'timestamp': time.time()
            }
            
            # Detect content domain if not specified
            if not self.domain_expertise:
                detected_domain = detect_content_domain(text, {})
                if detected_domain != 'general':
                    result['detected_domain'] = detected_domain
                    # Dynamically apply domain analysis
                    temp_analyzer = get_domain_analyzer(detected_domain)
                    domain_data = temp_analyzer.analyze_social_content(result)
                    result.update(domain_data)
            
            return result
            
        except Exception as e:
            logger.error(f"Error processing tweet {url}: {str(e)}")
            return {
                'url': url,
                'content_type': 'social',
                'social_platform': 'twitter',
                'error': str(e),
                'timestamp': time.time()
            }
    
    def _get_pdf_urls(self, query: str, max_results: int = 10) -> List[str]:
        """
        Get URLs for PDFs related to the query.
        
        Args:
            query: Search query
            max_results: Maximum number of results
            
        Returns:
            list: PDF URLs
        """
        try:
            from ..search.bing import search_bing
            
            # Add domain expertise to query if specified
            search_query = f"{query} filetype:pdf"
            if self.domain_expertise:
                search_query = f"{query} {self.domain_expertise} filetype:pdf"
                
            # Search specifically for PDFs
            results = search_bing(search_query, num_results=max_results)
            
            # Extract URLs
            urls = [result['url'] for result in results if result['url'].lower().endswith('.pdf')]
            
            # If we don't have enough results, try common sources
            if len(urls) < max_results:
                # Common sources for various domains
                common_sources = {
                    'marketing': [
                        'hubspot.com', 'marketo.com', 'salesforce.com', 'adobe.com', 'oracle.com'
                    ],
                    'legal': [
                        'justia.com', 'law.cornell.edu', 'findlaw.com', 'lexisnexis.com', 'westlaw.com'
                    ],
                    'academic': [
                        'researchgate.net', 'academia.edu', 'jstor.org', 'arxiv.org', 'sciencedirect.com'
                    ],
                    'general': [
                        'pdf.org', 'pdfdrive.com', 'scribd.com', 'slideshare.net', 'issuu.com'
                    ]
                }
                
                # Get sources for the domain or use general sources
                domain_sources = common_sources.get(self.domain_expertise or 'general', common_sources['general'])
                
                for source in domain_sources:
                    if len(urls) >= max_results:
                        break
                    
                    source_query = f"site:{source} {query} filetype:pdf"
                    source_results = search_bing(source_query, num_results=3)
                    source_urls = [result['url'] for result in source_results 
                                  if result['url'].lower().endswith('.pdf')]
                    urls.extend(source_urls)
            
            return urls[:max_results]
            
        except Exception as e:
            logger.error(f"Error getting PDF URLs: {str(e)}")
            return []
    
    def _get_video_urls(self, query: str, max_results: int = 10) -> List[str]:
        """
        Get URLs for videos related to the query.
        
        Args:
            query: Search query
            max_results: Maximum number of results
            
        Returns:
            list: Video URLs
        """
        try:
            from ..search.bing import search_bing
            
            # Add domain expertise to query if specified
            search_query = f"{query} site:youtube.com"
            if self.domain_expertise:
                search_query = f"{query} {self.domain_expertise} site:youtube.com"
                
            # Search for videos
            results = search_bing(search_query, num_results=max_results)
            
            # Extract URLs
            urls = [result['url'] for result in results 
                  if 'youtube.com/watch' in result['url'] or 'youtu.be/' in result['url']]
            
            # If we don't have enough results, try common channels in the domain
            if len(urls) < max_results and self.domain_expertise:
                # Common channels for various domains
                common_channels = {
                    'marketing': [
                        'hubspot', 'neilpatel', 'ahrefs', 'marketingprofs', 'semrush'
                    ],
                    'legal': [
                        'lawschool', 'legaleagle', 'lexisnexis', 'barbri', 'quimbee'
                    ],
                    'academic': [
                        'mit', 'stanford', 'harvard', 'khanacademy', 'crashcourse'
                    ]
                }
                
                domain_channels = common_channels.get(self.domain_expertise, [])
                
                for channel in domain_channels:
                    if len(urls) >= max_results:
                        break
                    
                    channel_query = f"site:youtube.com {channel} {query}"
                    channel_results = search_bing(channel_query, num_results=2)
                    channel_urls = [result['url'] for result in channel_results 
                                  if 'youtube.com/watch' in result['url'] or 'youtu.be/' in result['url']]
                    urls.extend(channel_urls)
            
            return urls[:max_results]
            
        except Exception as e:
            logger.error(f"Error getting video URLs: {str(e)}")
            return []
    
    def _get_podcast_urls(self, query: str, max_results: int = 10) -> List[str]:
        """
        Get URLs for podcasts related to the query.
        
        Args:
            query: Search query
            max_results: Maximum number of results
            
        Returns:
            list: Podcast URLs
        """
        try:
            from ..search.bing import search_bing
            
            # Add domain expertise to query if specified
            search_query = f"{query} podcast episode site:anchor.fm OR site:podcasts.apple.com OR site:spotify.com"
            if self.domain_expertise:
                search_query = f"{query} {self.domain_expertise} podcast episode site:anchor.fm OR site:podcasts.apple.com OR site:spotify.com"
                
            # Search for podcasts
            results = search_bing(search_query, num_results=max_results)
            
            # Extract URLs for known podcast platforms
            podcast_domains = ['anchor.fm', 'podcasts.apple.com', 'spotify.com/episode', 'buzzsprout.com', 'libsyn.com']
            urls = [result['url'] for result in results if any(domain in result['url'] for domain in podcast_domains)]
            
            return urls[:max_results]
            
        except Exception as e:
            logger.error(f"Error getting podcast URLs: {str(e)}")
            return []
    
    def _search_social_content(self, query: str, max_results: int = 100) -> List[Dict[str, Any]]:
        """
        Search for social media content.
        
        Args:
            query: Search query
            max_results: Maximum number of results
            
        Returns:
            list: Social media content
        """
        try:
            return self.tweet_scraper.search_tweets(query, max_results=max_results)
        except Exception as e:
            logger.error(f"Error searching social content: {str(e)}")
            return []
    
    def _search_datasets(self, query: str, max_results: int = 10) -> List[Dict[str, Any]]:
        """
        Search for datasets related to the query.
        
        Args:
            query: Search query
            max_results: Maximum number of results
            
        Returns:
            list: Dataset metadata
        """
        try:
            # Use domain-specific dataset search method if available
            if self.domain_expertise == 'marketing':
                return self.dataset_collector.extract_marketing_datasets(query)[:max_results]
            else:
                # General dataset search
                kaggle_results = self.dataset_collector.search_kaggle_datasets(query, max_results=max_results)
                
                for result in kaggle_results:
                    result['source'] = 'kaggle'
                
                return kaggle_results[:max_results]
                
        except Exception as e:
            logger.error(f"Error searching datasets: {str(e)}")
            return []