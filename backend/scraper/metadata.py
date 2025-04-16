import logging
import json
from typing import Dict, Any, Optional
from newspaper import Article, Config
from bs4 import BeautifulSoup
import trafilatura
from datetime import datetime
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

class ArticleSchema(BaseModel):
    """Schema for structured article data extraction."""
    title: str = Field(description="The title of the article")
    authors: list[str] = Field(default_factory=list, description="List of authors")
    published_date: Optional[str] = Field(None, description="Publication date")
    summary: Optional[str] = Field(None, description="Brief summary of the article")
    text: str = Field(description="Main text content")
    top_image: Optional[str] = Field(None, description="URL of the main image")
    keywords: list[str] = Field(default_factory=list, description="Keywords/tags")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


def extract_metadata(url, html=None):
    """
    Extract metadata from a web page using newspaper3k with trafilatura fallback.
    
    Args:
        url: The URL of the page
        html: Optional HTML content (if already fetched)
        
    Returns:
        dict: Extracted metadata
    """
    # Configuration for newspaper
    config = Config()
    config.browser_user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    config.request_timeout = 100
    config.fetch_images = False  # Skip image downloading for speed
    
    try:
        # First try with newspaper3k
        article = Article(url, config=config)
        
        if html:
            article.set_html(html)
            article.parse()
        else:
            article.download()
            article.parse()
            
        # Try to get nlp-derived data if possible
        try:
            article.nlp()
        except Exception as e:
            logger.debug(f"NLP processing failed: {str(e)}")
            
        metadata = {
            'title': article.title,
            'authors': article.authors,
            'published_date': article.publish_date.isoformat() if article.publish_date else None,
            'text': article.text,
            'top_image': article.top_image,
            'keywords': article.keywords,
            'summary': article.summary,
        }
        
        # If newspaper extraction returned empty content, try trafilatura
        if not metadata['text'] or len(metadata['text']) < 100:
            logger.debug("Newspaper returned limited text, trying trafilatura")
            metadata = fallback_trafilatura(url, html)
            
        return metadata
        
    except Exception as e:
        logger.warning(f"Newspaper extraction failed: {str(e)}, trying trafilatura")
        return fallback_trafilatura(url, html)
        
def fallback_trafilatura(url, html=None):
    """Fallback to trafilatura for content extraction when newspaper fails."""
    try:
        # Use the provided HTML or download it
        if not html:
            import requests
            response = requests.get(url, timeout=100, 
                                   headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})
            html = response.text
            
        # Extract main content
        extracted = trafilatura.extract(html, url=url, include_comments=False, 
                                       include_tables=True, include_images=True,
                                       output_format='json')
                                       
        if extracted:
            data = json.loads(extracted)
            return {
                'title': data.get('title', ''),
                'authors': [data.get('author', '')] if data.get('author') else [],
                'published_date': data.get('date', ''),
                'text': data.get('text', ''),
                'top_image': '',  # Trafilatura doesn't extract images URLs directly
                'keywords': [],
                'summary': data.get('description', ''),
            }
        else:
            # Last resort: basic extraction with BeautifulSoup
            return basic_extraction(html, url)
            
    except Exception as e:
        logger.error(f"Trafilatura extraction failed: {str(e)}")
        return basic_extraction(html, url)
        
def basic_extraction(html, url):
    """Very basic extraction with BeautifulSoup when all else fails."""
    try:
        soup = BeautifulSoup(html, 'html.parser')
        
        # Extract title
        title = ""
        title_tag = soup.find('title')
        if title_tag:
            title = title_tag.text.strip()
            
        # Try to get main content using common content div patterns
        content = ""
        content_candidates = soup.select('article, [role="main"], .post-content, .entry-content, #content, .content, main')
        
        if content_candidates:
            # Use the largest content block
            content_candidate = max(content_candidates, key=lambda x: len(x.text))
            content = content_candidate.text
        else:
            # Fallback to body text with some cleanup
            body = soup.find('body')
            if body:
                # Remove script and style elements
                for element in body.select('script, style, nav, header, footer'):
                    element.extract()
                content = body.text
                
        # Clean up whitespace
        content = ' '.join(content.split())
        
        return {
            'title': title,
            'authors': [],
            'published_date': None,
            'text': content,
            'top_image': '',
            'keywords': [],
            'summary': '',
        }
        
    except Exception as e:
        logger.error(f"Basic extraction failed: {str(e)}")
        return {
            'title': '',
            'authors': [],
            'published_date': None,
            'text': '',
            'top_image': '',
            'keywords': [],
            'summary': '',
        }

def extract_structured_data(html, url=None):
    """Extract structured data from a webpage (JSON-LD, microdata, etc.)"""
    try:
        soup = BeautifulSoup(html, 'html.parser')
        structured_data = []
        
        # Extract JSON-LD
        for script in soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string)
                structured_data.append(data)
            except:
                pass
                
        # Extract OpenGraph tags
        og_data = {}
        for meta in soup.find_all('meta', property=lambda x: x and x.startswith('og:')):
            property_name = meta.get('property', '')[3:]  # Remove 'og:' prefix
            if property_name and meta.get('content'):
                og_data[property_name] = meta.get('content')
                
        if og_data:
            structured_data.append({'@type': 'OpenGraph', 'properties': og_data})
            
        # Extract Twitter card
        twitter_data = {}
        for meta in soup.find_all('meta', attrs={'name': lambda x: x and x.startswith('twitter:')}):
            property_name = meta.get('name', '')[8:]  # Remove 'twitter:' prefix
            if property_name and meta.get('content'):
                twitter_data[property_name] = meta.get('content')
                
        if twitter_data:
            structured_data.append({'@type': 'TwitterCard', 'properties': twitter_data})
            
        return structured_data
    except Exception as e:
        logger.error(f"Error extracting structured data: {str(e)}")
        return []