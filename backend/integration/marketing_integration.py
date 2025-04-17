"""
Integration module to connect the marketing data collection tools with the WebIntel platform.
This module maps the collected marketing data to the appropriate WebIntel data models and
provides utilities for scraping, storing, and searching marketing content.
"""

import logging
import time
import json
import os
from typing import Dict, Any, List, Optional, Union, Callable
from urllib.parse import urlparse
from datetime import datetime

from ..models import ScrapeRun, ScrapedPage, PageLink
from ..scraper.marketing_handler import MarketingDataHandler
from ..search.vector_store import get_vector_store
from ..db.init_db import get_db

logger = logging.getLogger(__name__)

class MarketingIntegration:
    """
    Integration class to connect marketing data collection with WebIntel.
    """
    
    def __init__(self, db_session=None):
        """
        Initialize the marketing integration.
        
        Args:
            db_session: Optional database session
        """
        self.db_session = db_session
        self.marketing_handler = MarketingDataHandler()
        self.vector_store = get_vector_store()
    
    def create_marketing_scrape_run(self, 
                                  query: str,
                                  sources: List[str] = None,
                                  max_items_per_source: int = 5) -> int:
        """
        Create a new marketing scrape run.
        
        Args:
            query: Marketing search query
            sources: List of sources to collect from
            max_items_per_source: Maximum items per source
            
        Returns:
            int: ScrapeRun ID
        """
        if sources is None:
            sources = ['web', 'pdf', 'social', 'video', 'podcast', 'dataset']
        
        # Create a database session if not provided
        if not self.db_session:
            db = next(get_db())
        else:
            db = self.db_session
        
        try:
            # Create scrape run record
            run = ScrapeRun(
                query=f"Marketing: {query}",
                status="pending",
                max_depth=2,  # Default for marketing runs
                config={
                    "marketing_query": query,
                    "sources": sources,
                    "max_items_per_source": max_items_per_source
                }
            )
            
            db.add(run)
            db.commit()
            
            logger.info(f"Created marketing scrape run with ID {run.id} for query: {query}")
            
            return run.id
            
        except Exception as e:
            logger.error(f"Error creating marketing scrape run: {str(e)}")
            db.rollback()
            raise
        finally:
            # Close session if we created it
            if not self.db_session:
                db.close()
    
    def execute_marketing_scrape(self, run_id: int) -> Dict[str, Any]:
        """
        Execute a marketing scrape run.
        
        Args:
            run_id: ScrapeRun ID
            
        Returns:
            dict: Summary of results
        """
        # Create a database session if not provided
        if not self.db_session:
            db = next(get_db())
        else:
            db = self.db_session
        
        try:
            # Get the run
            run = db.query(ScrapeRun).filter(ScrapeRun.id == run_id).first()
            
            if not run:
                raise ValueError(f"ScrapeRun not found with ID: {run_id}")
            
            # Update status
            run.status = "running"
            run.updated_at = datetime.utcnow()
            db.commit()
            
            # Get configuration
            config = run.config or {}
            query = config.get("marketing_query", run.query)
            sources = config.get("sources", ['web', 'pdf', 'social', 'video', 'podcast', 'dataset'])
            max_items_per_source = config.get("max_items_per_source", 5)
            
            logger.info(f"Executing marketing scrape for run {run_id}, query: {query}")
            
            # Define callback to save items as they're collected
            def save_item_callback(source_type, item):
                try:
                    self._save_marketing_item(db, run_id, source_type, item)
                except Exception as e:
                    logger.error(f"Error saving {source_type} item: {str(e)}")
            
            # Execute the scrape
            results = self.marketing_handler.collect_marketing_data(
                query=query,
                sources=sources,
                max_items_per_source=max_items_per_source,
                callback=save_item_callback
            )
            
            # Update run stats
            run.pages_crawled = db.query(ScrapedPage).filter(ScrapedPage.scrape_run_id == run_id).count()
            run.status = "completed"
            run.completed_at = datetime.utcnow()
            db.commit()
            
            # Prepare summary
            summary = {
                "run_id": run_id,
                "query": query,
                "sources": sources,
                "items_collected": {source: len(items) for source, items in results.items()},
                "total_items": sum(len(items) for items in results.values()),
                "completed_at": run.completed_at.isoformat() if run.completed_at else None
            }
            
            logger.info(f"Marketing scrape {run_id} completed with {summary['total_items']} items")
            
            return summary
            
        except Exception as e:
            logger.error(f"Error executing marketing scrape: {str(e)}")
            
            # Update run status to failed
            if run:
                run.status = "failed"
                run.updated_at = datetime.utcnow()
                db.commit()
            
            raise
        finally:
            # Close session if we created it
            if not self.db_session:
                db.close()
    
    def process_marketing_url(self, url: str, run_id: Optional[int] = None) -> int:
        """
        Process a single marketing URL and save to the database.
        
        Args:
            url: URL to process
            run_id: Optional ScrapeRun ID (creates a new one if not provided)
            
        Returns:
            int: ScrapedPage ID
        """
        # Create a database session if not provided
        if not self.db_session:
            db = next(get_db())
        else:
            db = self.db_session
        
        try:
            # Create run if not provided
            if not run_id:
                run = ScrapeRun(
                    query=f"Marketing URL: {url}",
                    status="running",
                    max_depth=0,
                    config={"marketing_url": url}
                )
                db.add(run)
                db.commit()
                run_id = run.id
            
            # Process the URL
            item = self.marketing_handler.process_url(url)
            
            # Determine the source type
            source_type = self._determine_source_type(url, item)
            
            # Save the item
            page_id = self._save_marketing_item(db, run_id, source_type, item)
            
            # Update run status if we created it
            if not run_id:
                run = db.query(ScrapeRun).filter(ScrapeRun.id == run_id).first()
                if run:
                    run.status = "completed"
                    run.completed_at = datetime.utcnow()
                    run.pages_crawled = 1
                    db.commit()
            
            return page_id
            
        except Exception as e:
            logger.error(f"Error processing marketing URL {url}: {str(e)}")
            db.rollback()
            raise
        finally:
            # Close session if we created it
            if not self.db_session:
                db.close()
    
    def search_marketing_content(self, query: str, run_id: Optional[int] = None, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Search for marketing content using vector similarity.
        
        Args:
            query: Search query
            run_id: Optional run ID to filter results
            limit: Maximum number of results
            
        Returns:
            list: Search results
        """
        try:
            logger.info(f"Searching marketing content for: {query}")
            
            # Use the vector store for semantic search
            search_results = self.vector_store.search(query, k=limit)
            
            # Filter by run_id if specified
            if run_id is not None:
                search_results = [
                    result for result in search_results 
                    if result.get('metadata', {}).get('run_id') == run_id
                ]
            
            # Format results
            formatted_results = []
            for result in search_results:
                formatted_results.append({
                    'doc_id': result['doc_id'],
                    'score': result['score'],
                    'title': result.get('metadata', {}).get('title', ''),
                    'url': result.get('metadata', {}).get('url', ''),
                    'source_type': result.get('metadata', {}).get('source_type', ''),
                    'content_type': result.get('metadata', {}).get('content_type', ''),
                    'page_id': result.get('metadata', {}).get('page_id')
                })
            
            return formatted_results
            
        except Exception as e:
            logger.error(f"Error searching marketing content: {str(e)}")
            return []
    
    def _save_marketing_item(self, db_session, run_id: int, source_type: str, item: Dict[str, Any]) -> int:
        """
        Save a marketing item to the database.
        
        Args:
            db_session: Database session
            run_id: ScrapeRun ID
            source_type: Source type
            item: Item data
            
        Returns:
            int: ScrapedPage ID
        """
        try:
            # Extract common fields
            url = item.get('url', '')
            title = item.get('title', 'Untitled')
            text = item.get('text', '') or item.get('transcript', '')  # For videos/podcasts
            
            # Create page record
            page = ScrapedPage(
                scrape_run_id=run_id,
                url=url,
                title=title,
                crawl_depth=0,  # Marketing items are always depth 0
                content_text=text,
                crawled_at=datetime.utcnow(),
                structured_data=item  # Store full item data
            )
            
            # Add specific metadata
            page_metadata = {
                'source_type': source_type,
                'timestamp': item.get('timestamp', time.time())
            }
            
            # Add content type if available
            content_type = (
                item.get('content_type') or 
                item.get('type') or 
                source_type
            )
            page_metadata['content_type'] = content_type
            
            # Add other important fields based on source type
            if source_type == 'web':
                page_metadata.update({
                    'authors': item.get('authors', []),
                    'published_date': item.get('published_date')
                })
            elif source_type == 'pdf':
                page_metadata.update({
                    'pages': item.get('pages'),
                    'author': item.get('author'),
                    'company': item.get('company')
                })
            elif source_type == 'social':
                page_metadata.update({
                    'social_platform': item.get('source_type'),
                    'author': item.get('author', {}).get('username') if isinstance(item.get('author'), dict) else None,
                    'engagement_metrics': {
                        'likes': item.get('like_count', 0),
                        'retweets': item.get('retweet_count', 0),
                        'replies': item.get('reply_count', 0)
                    }
                })
            elif source_type in ['video', 'podcast']:
                page_metadata.update({
                    'duration': item.get('duration', 0),
                    'channel': item.get('channel') or item.get('uploader'),
                    'published_date': item.get('upload_date'),
                    'view_count': item.get('view_count', 0)
                })
            elif source_type == 'dataset':
                page_metadata.update({
                    'dataset_name': item.get('name') or item.get('title'),
                    'dataset_source': item.get('source'),
                    'dataset_size': item.get('size'),
                    'dataset_downloads': item.get('downloads') or item.get('downloadCount', 0)
                })
            
            page.page_metadata = page_metadata
            
            # Add to database
            db_session.add(page)
            db_session.flush()  # Get ID without committing
            
            # Add to vector store if there's text content
            if text:
                doc_id = f"page_{page.id}"
                metadata = {
                    'page_id': page.id,
                    'run_id': run_id,
                    'url': url,
                    'title': title,
                    'source_type': source_type,
                    'content_type': content_type
                }
                
                self.vector_store.add(doc_id, text, metadata=metadata)
                page.embedding_id = doc_id
            
            # Create links if available
            if 'links' in item and isinstance(item['links'], list):
                for link_data in item['links']:
                    link_url = link_data.get('url', '')
                    if link_url:
                        # Determine if internal
                        base_domain = urlparse(url).netloc
                        link_domain = urlparse(link_url).netloc
                        is_internal = base_domain == link_domain
                        
                        link = PageLink(
                            page_id=page.id,
                            url=link_url,
                            anchor_text=link_data.get('anchor_text', ''),
                            is_internal=link_data.get('is_internal', is_internal),
                            is_crawled=False
                        )
                        db_session.add(link)
            
            # Commit
            db_session.commit()
            
            logger.info(f"Saved {source_type} item: {title} (ID: {page.id})")
            
            return page.id
            
        except Exception as e:
            db_session.rollback()
            logger.error(f"Error saving marketing item: {str(e)}")
            raise
    
    def _determine_source_type(self, url: str, item: Dict[str, Any]) -> str:
        """
        Determine the source type based on URL and item data.
        
        Args:
            url: URL
            item: Item data
            
        Returns:
            str: Source type
        """
        # Check if already specified
        if 'type' in item:
            item_type = item['type']
            if item_type in ['pdf', 'podcast', 'lecture', 'webinar']:
                if item_type == 'lecture' or item_type == 'webinar':
                    return 'video'
                return item_type
        
        # Check URL
        url_lower = url.lower()
        if url_lower.endswith('.pdf'):
            return 'pdf'
        elif 'youtube.com' in url_lower or 'youtu.be' in url_lower:
            return 'video'
        elif any(domain in url_lower for domain in ['twitter.com', 'x.com']):
            return 'social'
        elif any(domain in url_lower for domain in ['anchor.fm', 'podcasts.apple.com', 'spotify.com/episode']):
            return 'podcast'
        elif any(domain in url_lower for domain in ['kaggle.com/datasets', 'huggingface.co/datasets']):
            return 'dataset'
        
        # Default to web
        return 'web'