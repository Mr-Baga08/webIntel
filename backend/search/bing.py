import logging
import re
import time
from bs4 import BeautifulSoup
from urllib.parse import quote_plus
from typing import List, Dict, Any, Optional

from ..scraper.base_scraper import BaseScraper

logger = logging.getLogger(__name__)

class BingSearchScraper:
    """
    Scraper for Bing search results using Playwright.
    Uses web scraping since the official Bing API requires an API key.
    """
    
    def __init__(self, proxy=None, user_agent=None):
        self.scraper = BaseScraper(
            headless=True,
            proxy=proxy,
            user_agent=user_agent,
            timeout=30000000
        )
        
    def search(self, query: str, num_results: int = 10) -> List[Dict[str, Any]]:
        """
        Perform a search on Bing and extract search results.
        
        Args:
            query: Search query
            num_results: Number of results to return (max 50)
            
        Returns:
            list: List of search result dictionaries
        """
        # Limit max results
        num_results = min(num_results, 50)
        
        # Create the search URL
        encoded_query = quote_plus(query)
        url = f"https://www.bing.com/search?q={encoded_query}&count={num_results}"
        
        logger.info(f"Searching Bing for: {query}")
        
        try:
            # Get the search results page
            html, _ = self.scraper.get_page_content(
                url,
                wait_for_selectors=["#b_results"]
            )
            
            if not html:
                logger.error("Failed to fetch Bing search results")
                return []
                
            # Parse the results
            results = self._parse_search_results(html, num_results)
            
            logger.info(f"Found {len(results)} results for query: {query}")
            return results
            
        except Exception as e:
            logger.error(f"Error while searching Bing: {str(e)}")
            return []
            
    def _parse_search_results(self, html: str, limit: int) -> List[Dict[str, Any]]:
        """
        Parse Bing search results from HTML.
        
        Args:
            html: HTML content of the search results page
            limit: Maximum number of results to return
            
        Returns:
            list: Parsed search results
        """
        soup = BeautifulSoup(html, 'html.parser')
        results = []
        
        # Find all search result entries
        for result in soup.select('li.b_algo')[:limit]:
            try:
                # Extract the link
                link_element = result.select_one('h2 a')
                if not link_element:
                    continue
                    
                link = link_element.get('href')
                title = link_element.get_text()
                
                # Extract the snippet
                snippet_element = result.select_one('.b_caption p')
                snippet = snippet_element.get_text() if snippet_element else ""
                
                # Extract the site name/domain if available
                site_element = result.select_one('cite')
                site = site_element.get_text() if site_element else ""
                
                results.append({
                    'title': title,
                    'url': link,
                    'snippet': snippet,
                    'site': site
                })
                
            except Exception as e:
                logger.debug(f"Error parsing search result: {str(e)}")
                continue
                
        return results

def search_bing(query: str, num_results: int = 5, proxy: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Helper function to search Bing without creating a BingSearchScraper instance.
    
    Args:
        query: Search query
        num_results: Number of results to return
        proxy: Optional proxy to use
        
    Returns:
        list: Search results
    """
    scraper = BingSearchScraper(proxy=proxy)
    return scraper.search(query, num_results=num_results)