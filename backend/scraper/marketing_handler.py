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

logger = logging.getLogger(__name__)

class MarketingDataHandler:
    """
    Unified handler for collecting marketing data from various sources.
    Integrates web scraping, PDF extraction, social media, multimedia, and datasets.
    """
    
    def __init__(self, 
                max_workers: int = 5,
                temp_dir: Optional[str] = None,
                keep_downloads: bool = False):
        """
        Initialize the marketing data handler.
        
        Args:
            max_workers: Maximum number of concurrent workers
            temp_dir: Directory for temporary files
            keep_downloads: Whether to keep downloaded files
        """
        self.max_workers = max_workers
        self.temp_dir = temp_dir
        self.keep_downloads = keep_downloads
        
        # Initialize components
        self.scraper = BaseScraper(headless=True)
        self.pdf_extractor = PDFExtractor(temp_dir=temp_dir)
        self.tweet_scraper = TwitterScraper()
        self.multimedia_extractor = MultimediaExtractor(temp_dir=temp_dir, keep_downloads=keep_downloads)
        self.dataset_collector = DatasetCollector(output_dir=temp_dir)
    
    def collect_marketing_data(self, 
                              query: str,
                              sources: List[str] = None,
                              max_items_per_source: int = 5,
                              callback: Optional[Callable] = None) -> Dict[str, List[Dict[str, Any]]]:
        """
        Collect marketing data from multiple sources based on a query.
        
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
        
        logger.info(f"Collecting marketing data for query: {query} from sources: {sources}")
        
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
                            results['web'].append(result)
                            if callback:
                                callback('web', result)
                    except Exception as e:
                        logger.error(f"Error processing web future: {str(e)}")
            
            # PDF extraction
            if 'pdf' in sources:
                logger.info("Collecting PDF content")
                pdf_futures = []
                
                # Get PDF URLs (search for PDFs or use known marketing PDF repositories)
                pdf_urls = self._get_pdf_urls(query, max_results=max_items_per_source)
                
                for url in pdf_urls:
                    future = executor.submit(self._process_pdf, url)
                    pdf_futures.append(future)
                
                # Process completed futures
                for future in pdf_futures:
                    try:
                        result = future.result()
                        if result:
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
                future = executor.submit(search_marketing_tweets, query, max_results=max_items_per_source)
                social_futures.append(('twitter', future))
                
                # Process completed futures
                for source_type, future in social_futures:
                    try:
                        items = future.result()
                        if items:
                            for item in items:
                                item['source_type'] = source_type
                                results['social'].append(item)
                                if callback:
                                    callback('social', item)
                    except Exception as e:
                        logger.error(f"Error processing social future: {str(e)}")
            
            # Video content
            if 'video' in sources:
                logger.info("Collecting video content")
                video_futures = []
                
                # Get marketing lecture videos
                video_urls = self._get_marketing_video_urls(query, max_results=max_items_per_source)
                
                for url in video_urls:
                    future = executor.submit(extract_youtube_lecture, url)
                    video_futures.append(future)
                
                # Process completed futures
                for future in video_futures:
                    try:
                        result = future.result()
                        if result and 'error' not in result:
                            results['video'].append(result)
                            if callback:
                                callback('video', result)
                    except Exception as e:
                        logger.error(f"Error processing video future: {str(e)}")
            
            # Podcast content
            if 'podcast' in sources:
                logger.info("Collecting podcast content")
                podcast_futures = []
                
                # Get marketing podcast episodes
                podcast_urls = self._get_marketing_podcast_urls(query, max_results=max_items_per_source)
                
                for url in podcast_urls:
                    future = executor.submit(extract_marketing_podcast, url)
                    podcast_futures.append(future)
                
                # Process completed futures
                for future in podcast_futures:
                    try:
                        result = future.result()
                        if result and 'error' not in result:
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
                    datasets = get_marketing_datasets(query)
                    results['dataset'] = datasets[:max_items_per_source]
                    
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
            return self._process_pdf(url)
        elif 'youtube.com' in url or 'youtu.be' in url:
            return extract_youtube_lecture(url)
        elif url.lower().endswith(('.mp3', '.m4a', '.wav')) or any(domain in url for domain in ['anchor.fm', 'podcasts.apple.com', 'spotify.com/episode']):
            return extract_marketing_podcast(url)
        else:
            # Default to web page
            return self._process_web_page(url)
    
    def download_marketing_dataset(self, dataset_info: Dict[str, Any]) -> Dict[str, Any]:
        """
        Download and process a marketing dataset.
        
        Args:
            dataset_info: Dataset metadata
            
        Returns:
            dict: Dataset content and metadata
        """
        try:
            dataframes = self.dataset_collector.load_marketing_dataset(dataset_info)
            
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
            
            return result
            
        except Exception as e:
            logger.error(f"Error downloading marketing dataset: {str(e)}")
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
            
            # Use existing Bing search from WebIntel
            results = search_bing(f"{query} marketing", num_results=max_results)
            
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
                'type': 'web_page',
                'title': content_metadata.get('title') or scrape_metadata.get('title', ''),
                'text': content_metadata.get('text', ''),
                'authors': content_metadata.get('authors', []),
                'published_date': content_metadata.get('published_date'),
                'structured_data': structured_data,
                'timestamp': time.time()
            }
            
            # Add original metadata if provided
            if metadata:
                result['search_metadata'] = metadata
            
            # Add marketing-specific data
            marketing_data = self._extract_marketing_web_data(result, html)
            result.update(marketing_data)
            
            return result
            
        except Exception as e:
            logger.error(f"Error processing web page {url}: {str(e)}")
            return {
                'url': url,
                'type': 'web_page',
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
                'type': 'pdf',
                'title': pdf_data.get('metadata', {}).get('title', 'Untitled PDF'),
                'text': pdf_data.get('text', ''),
                'author': pdf_data.get('metadata', {}).get('author', ''),
                'pages': len(pdf_data.get('pages', [])),
                'tables': pdf_data.get('tables', []),
                'timestamp': time.time()
            }
            
            # Copy marketing-specific data if available
            marketing_keys = ['type', 'company', 'challenge', 'solution', 'results', 
                            'executive_summary', 'key_findings']
            
            for key in marketing_keys:
                if key in pdf_data:
                    result[key] = pdf_data[key]
            
            return result
            
        except Exception as e:
            logger.error(f"Error processing PDF {url}: {str(e)}")
            return {
                'url': url,
                'type': 'pdf',
                'error': str(e),
                'timestamp': time.time()
            }
    
    def _get_pdf_urls(self, query: str, max_results: int = 10) -> List[str]:
        """
        Get URLs for marketing PDFs.
        
        Args:
            query: Search query
            max_results: Maximum number of results
            
        Returns:
            list: PDF URLs
        """
        try:
            from ..search.bing import search_bing
            
            # Search specifically for PDFs
            pdf_query = f"{query} filetype:pdf marketing"
            results = search_bing(pdf_query, num_results=max_results)
            
            # Extract URLs
            urls = [result['url'] for result in results if result['url'].lower().endswith('.pdf')]
            
            # If we don't have enough results, try common marketing PDF sources
            if len(urls) < max_results:
                # Common sources for marketing case studies and whitepapers
                common_sources = [
                    'hbr.org',
                    'mckinsey.com',
                    'deloitte.com',
                    'forrester.com',
                    'gartner.com',
                    'hubspot.com',
                    'marketo.com',
                    'salesforce.com',
                    'adobe.com',
                    'oracle.com'
                ]
                
                for source in common_sources:
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
    
    def _get_marketing_video_urls(self, query: str, max_results: int = 10) -> List[str]:
        """
        Get URLs for marketing lecture videos.
        
        Args:
            query: Search query
            max_results: Maximum number of results
            
        Returns:
            list: Video URLs
        """
        try:
            from ..search.bing import search_bing
            
            # Search for marketing lectures on YouTube
            video_query = f"{query} marketing lecture OR course OR tutorial site:youtube.com"
            results = search_bing(video_query, num_results=max_results)
            
            # Extract URLs
            urls = [result['url'] for result in results 
                  if 'youtube.com/watch' in result['url'] or 'youtu.be/' in result['url']]
            
            # If we don't have enough results, try common marketing channels
            if len(urls) < max_results:
                # Common marketing educational channels
                channels = [
                    'hubspot',
                    'neilpatel',
                    'ahrefs',
                    'marketingprofs',
                    'semrush',
                    'wistia',
                    'moz',
                    'contentmarketinginstitute',
                    'hootsuite',
                    'buffer'
                ]
                
                for channel in channels:
                    if len(urls) >= max_results:
                        break
                    
                    channel_query = f"site:youtube.com {channel} {query} marketing"
                    channel_results = search_bing(channel_query, num_results=2)
                    channel_urls = [result['url'] for result in channel_results 
                                  if 'youtube.com/watch' in result['url'] or 'youtu.be/' in result['url']]
                    urls.extend(channel_urls)
            
            return urls[:max_results]
            
        except Exception as e:
            logger.error(f"Error getting marketing video URLs: {str(e)}")
            return []
    
    def _get_marketing_podcast_urls(self, query: str, max_results: int = 10) -> List[str]:
        """
        Get URLs for marketing podcast episodes.
        
        Args:
            query: Search query
            max_results: Maximum number of results
            
        Returns:
            list: Podcast URLs
        """
        try:
            from ..search.bing import search_bing
            
            # Search for marketing podcasts
            podcast_query = f"{query} marketing podcast episode site:anchor.fm OR site:podcasts.apple.com OR site:spotify.com"
            results = search_bing(podcast_query, num_results=max_results)
            
            # Extract URLs for known podcast platforms
            podcast_domains = ['anchor.fm', 'podcasts.apple.com', 'spotify.com/episode', 'buzzsprout.com', 'libsyn.com']
            urls = [result['url'] for result in results if any(domain in result['url'] for domain in podcast_domains)]
            
            # If we don't have enough results, search for top marketing podcasts
            if len(urls) < max_results:
                # Top marketing podcasts
                podcasts = [
                    'marketing school',
                    'marketing over coffee',
                    'social media marketing',
                    'perpetual traffic',
                    'the marketing companion',
                    'call to action',
                    'copyblogger fm',
                    'marketing made simple'
                ]
                
                for podcast in podcasts:
                    if len(urls) >= max_results:
                        break
                    
                    podcast_query = f"\"{podcast}\" episode {query}"
                    podcast_results = search_bing(podcast_query, num_results=2)
                    podcast_urls = [result['url'] for result in podcast_results 
                                   if any(domain in result['url'] for domain in podcast_domains)]
                    urls.extend(podcast_urls)
            
            return urls[:max_results]
            
        except Exception as e:
            logger.error(f"Error getting marketing podcast URLs: {str(e)}")
            return []
    
    def _extract_marketing_web_data(self, page_data: Dict[str, Any], html: str) -> Dict[str, Any]:
        """
        Extract marketing-specific data from a web page.
        
        Args:
            page_data: Page data
            html: HTML content
            
        Returns:
            dict: Marketing-specific data
        """
        marketing_data = {}
        
        # Check if it's a case study
        title = page_data.get('title', '').lower()
        text = page_data.get('text', '').lower()
        
        if 'case study' in title or 'case study' in text[:1000]:
            marketing_data['content_type'] = 'case_study'
            
            # Try to extract company name
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, 'html.parser')
            
            # Look for company in schema.org data
            for script in soup.find_all('script', {'type': 'application/ld+json'}):
                try:
                    ld_json = json.loads(script.string)
                    if isinstance(ld_json, dict):
                        # Look for organization
                        if ld_json.get('@type') == 'Organization':
                            marketing_data['company'] = ld_json.get('name')
                        # Look for article publisher
                        elif ld_json.get('@type') == 'Article' and isinstance(ld_json.get('publisher'), dict):
                            publisher = ld_json.get('publisher')
                            if publisher.get('@type') == 'Organization':
                                marketing_data['company'] = publisher.get('name')
                except Exception:
                    pass
            
            # Try to find sections (challenge, solution, results)
            sections = {}
            section_headings = soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
            
            for heading in section_headings:
                heading_text = heading.get_text().lower()
                
                if any(term in heading_text for term in ['challenge', 'problem', 'situation']):
                    # Get text until next heading
                    content = []
                    for sibling in heading.next_siblings:
                        if sibling.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
                            break
                        if sibling.get_text().strip():
                            content.append(sibling.get_text().strip())
                    sections['challenge'] = ' '.join(content)
                    
                elif any(term in heading_text for term in ['solution', 'approach', 'strategy']):
                    content = []
                    for sibling in heading.next_siblings:
                        if sibling.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
                            break
                        if sibling.get_text().strip():
                            content.append(sibling.get_text().strip())
                    sections['solution'] = ' '.join(content)
                    
                elif any(term in heading_text for term in ['result', 'outcome', 'impact']):
                    content = []
                    for sibling in heading.next_siblings:
                        if sibling.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
                            break
                        if sibling.get_text().strip():
                            content.append(sibling.get_text().strip())
                    sections['results'] = ' '.join(content)
            
            # Add sections to marketing data
            marketing_data.update(sections)
            
        elif any(term in title.lower() for term in ['blog', 'article']):
            marketing_data['content_type'] = 'blog_post'
            
        elif any(term in title.lower() for term in ['whitepaper', 'white paper', 'report', 'study']):
            marketing_data['content_type'] = 'whitepaper'
            
        else:
            # Default content type
            marketing_data['content_type'] = 'web_page'
        
        return marketing_data