import logging
import re
import time
import yaml
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
from pydantic import BaseModel, Field
from typing import List, Dict, Set, Optional, Any
import threading

from .base_scraper import BaseScraper
from .controller import scrape_control
from .metadata import extract_metadata

logger = logging.getLogger(__name__)

class CrawlConfig(BaseModel):
    """Pydantic model for crawler configuration."""
    start_urls: List[str]
    allowed_domains: Optional[List[str]] = None
    max_depth: int = 2
    max_pages: int = 100
    follow_external_links: bool = False
    wait_time: float = 0.5  # Time to wait between requests
    css_selectors: Optional[Dict[str, str]] = None
    proxy: Optional[str] = None
    user_agent: Optional[str] = None

class Crawler:
    """Multi-level web crawler with configurable depth and domain filtering."""
    
    def __init__(self, job_id, config=None, db_session=None):
        """
        Initialize the crawler.
        
        Args:
            job_id: Unique identifier for this crawl job
            config: CrawlConfig or dict with crawler configuration
            db_session: SQLAlchemy database session for storing results
        """
        self.job_id = job_id
        
        # Convert dict to CrawlConfig if needed
        if isinstance(config, dict):
            self.config = CrawlConfig(**config)
        elif config is None:
            self.config = CrawlConfig(start_urls=[])
        else:
            self.config = config
            
        self.db_session = db_session
        self.scraper = BaseScraper(
            headless=True,
            proxy=self.config.proxy,
            user_agent=self.config.user_agent
        )
        
        # State tracking
        self.visited_urls = set()
        self.queued_urls = set()
        self.failed_urls = set()
        self.results = []
        
        # Register with controller
        scrape_control.register_job(job_id)
        
    def is_allowed_domain(self, url):
        """Check if the URL's domain is in the allowed domains list."""
        if not self.config.allowed_domains:
            return True
            
        domain = urlparse(url).netloc
        return any(allowed in domain for allowed in self.config.allowed_domains)
    
    def extract_links(self, html, base_url):
        """Extract links from HTML content."""
        soup = BeautifulSoup(html, 'html.parser')
        links = []
        
        for a in soup.find_all('a', href=True):
            href = a['href']
            
            # Skip empty links, javascript, mailto, etc.
            if not href or href.startswith(('javascript:', 'mailto:', 'tel:', '#')):
                continue
                
            # Resolve relative URLs
            if not href.startswith(('http://', 'https://')):
                href = urljoin(base_url, href)
                
            # Check if this is an external link
            base_domain = urlparse(base_url).netloc
            link_domain = urlparse(href).netloc
            
            is_external = base_domain != link_domain
            
            # Skip external links if not following them
            if is_external and not self.config.follow_external_links:
                continue
                
            # Skip links to non-allowed domains
            if not self.is_allowed_domain(href):
                continue
                
            # Add anchor text if available
            anchor_text = a.text.strip() if a.text else ""
            
            links.append({
                'url': href,
                'anchor_text': anchor_text,
                'is_internal': not is_external
            })
            
        return links
    
    def crawl_url(self, url, depth=0):
        """
        Crawl a single URL and extract content and links.
        
        Args:
            url: URL to crawl
            depth: Current crawl depth
            
        Returns:
            dict: Page data including content and extracted links
        """
        # Check if we should continue
        if not scrape_control.should_continue(self.job_id):
            return None
            
        # Check if we should pause
        while scrape_control.is_paused(self.job_id):
            time.sleep(1)
            if not scrape_control.should_continue(self.job_id):
                return None
        
        # Skip if already visited
        if url in self.visited_urls:
            return None
            
        # Mark as visited
        self.visited_urls.add(url)
        
        logger.info(f"Crawling {url} (depth={depth})")
        
        try:
            # Get page content using PlayWright
            html, basic_metadata = self.scraper.get_page_content(
                url, 
                wait_for_selectors=self.config.css_selectors.values() if self.config.css_selectors else None
            )
            
            if not html:
                self.failed_urls.add(url)
                return None
                
            # Extract metadata using newspaper3k
            metadata = extract_metadata(url, html)
            
            # Extract links for further crawling
            links = self.extract_links(html, url)
            
            # Create result object
            result = {
                'url': url,
                'depth': depth,
                'html': html,
                'title': metadata.get('title', basic_metadata.get('title', '')),
                'text': metadata.get('text', ''),
                'metadata': metadata,
                'links': links
            }
            
            # Wait between requests to be polite
            time.sleep(self.config.wait_time)
            
            return result
            
        except Exception as e:
            logger.error(f"Error crawling {url}: {str(e)}")
            self.failed_urls.add(url)
            return None
    
    def crawl(self, callback=None):
        """
        Start crawling from the configured start URLs.
        
        Args:
            callback: Optional function to call with each crawled page
            
        Returns:
            list: All crawled results
        """
        # Queue start URLs
        url_queue = [(url, 0) for url in self.config.start_urls]
        self.queued_urls.update(self.config.start_urls)
        
        # Start the controller
        scrape_control.start(self.job_id)
        
        pages_crawled = 0
        
        # Process queue
        while url_queue and scrape_control.should_continue(self.job_id):
            # Check if we've reached the max pages
            if pages_crawled >= self.config.max_pages:
                logger.info(f"Reached maximum pages limit: {self.config.max_pages}")
                break
                
            # Get next URL from queue
            url, depth = url_queue.pop(0)
            
            # Skip if too deep
            if depth > self.config.max_depth:
                continue
                
            # Crawl the URL
            result = self.crawl_url(url, depth)
            
            if result:
                self.results.append(result)
                pages_crawled += 1
                
                # Update controller stats
                scrape_control.update_stats(self.job_id, pages_crawled=pages_crawled)
                
                # Call callback if provided
                if callback:
                    callback(result)
                    
                # Add links to queue if not at max depth
                if depth < self.config.max_depth:
                    for link in result['links']:
                        link_url = link['url']
                        if (link_url not in self.visited_urls and 
                            link_url not in self.queued_urls and
                            link_url not in self.failed_urls):
                            url_queue.append((link_url, depth + 1))
                            self.queued_urls.add(link_url)
        
        # Mark job as completed
        if scrape_control.should_continue(self.job_id):
            scrape_control.complete(self.job_id)
        
        return self.results

    @classmethod
    def from_yaml_config(cls, job_id, yaml_str, db_session=None):
        """Create a crawler from YAML configuration string."""
        try:
            config_dict = yaml.safe_load(yaml_str)
            return cls(job_id, config=config_dict, db_session=db_session)
        except Exception as e:
            logger.error(f"Error parsing YAML config: {str(e)}")
            raise ValueError(f"Invalid YAML configuration: {str(e)}")

def crawl_with_config(job_id, config, db_session=None, callback=None):
    """
    Helper function to start a crawl job with the given configuration.
    
    Args:
        job_id: Unique identifier for this crawl job
        config: Dict or CrawlConfig with crawler configuration
        db_session: SQLAlchemy database session
        callback: Optional function to call with each crawled page
        
    Returns:
        list: Crawled results
    """
    crawler = Crawler(job_id, config, db_session)
    return crawler.crawl(callback=callback)