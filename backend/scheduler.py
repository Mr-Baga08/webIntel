import logging
import threading
from datetime import datetime
from typing import Dict, Any, Callable, Optional
import yaml

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.schedulers.base import SchedulerNotRunningError

from sqlalchemy.orm import Session

from .scraper.crawler import Crawler
from .scraper.controller import scrape_control
from .search.bing import search_bing
from .search.ranker import rank_search_results
from .db.init_db import get_db
from .models import ScrapeRun, ScrapedPage, PageLink

logger = logging.getLogger(__name__)

class WebIntelScheduler:
    """
    Scheduler for handling background scraping jobs.
    Uses APScheduler for job management.
    """
    
    def __init__(self, max_workers=5):
        """
        Initialize the scheduler.
        
        Args:
            max_workers: Maximum number of concurrent worker threads
        """
        # Configure scheduler
        jobstores = {
            'default': MemoryJobStore()
        }
        
        executors = {
            'default': ThreadPoolExecutor(max_workers)
        }
        
        job_defaults = {
            'coalesce': False,
            'max_instances': max_workers
        }
        
        # Create scheduler
        self.scheduler = BackgroundScheduler(
            jobstores=jobstores,
            executors=executors,
            job_defaults=job_defaults
        )
        
        # Track running jobs
        self.jobs = {}
        self.lock = threading.Lock()
        self.running = False
        
    def start(self):
        """Start the scheduler."""
        try:
            if not self.running:
                self.scheduler.start()
                self.running = True
                logger.info("Scheduler started")
                # Check for existing jobs in the database and schedule them
                self._schedule_pending_jobs()
            else:
                logger.info("Scheduler already running")
        except Exception as e:
            logger.error(f"Error starting scheduler: {str(e)}")
            self.running = False
            
    def _schedule_pending_jobs(self):
        """Look for pending jobs in the database."""
        try:
            logger.info("Checking for pending jobs in the database")
            db = next(get_db())
            try:
                pending_runs = db.query(ScrapeRun).filter(ScrapeRun.status == 'pending').all()
                logger.info(f"Found {len(pending_runs)} pending jobs")
                
                for run in pending_runs:
                    logger.info(f"Scheduling pending job for run_id={run.id}, query={run.query}")
                    self.schedule_scrape_job(run.id, run.query, run.max_depth, config=run.config)
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Error scheduling pending jobs: {str(e)}")
        
    def shutdown(self):
        """Shutdown the scheduler."""
        if self.running:
            try:
                self.scheduler.shutdown()
                self.running = False
                logger.info("Scheduler shut down")
            except SchedulerNotRunningError:
                logger.warning("Scheduler was already shut down")
                self.running = False
            except Exception as e:
                logger.error(f"Error shutting down scheduler: {str(e)}")
                self.running = False
        
    def schedule_scrape_job(self, run_id: int, query: str, max_depth: int = 2, 
                           db_session: Optional[Session] = None,
                           config: Optional[Dict[str, Any]] = None):
        """
        Schedule a new scraping job.
        
        Args:
            run_id: Scrape run ID
            query: Search query
            max_depth: Maximum crawl depth
            db_session: SQLAlchemy database session
            config: Optional configuration for the crawler
            
        Returns:
            str: Job ID
        """
        try:
            logger.info(f"Scheduling scrape job for query: {query}")
            
            # Create job ID
            job_id = f"scrape_{run_id}"
            
            # Register job with scraper controller
            scrape_control.register_job(job_id)
            
            # Add job to scheduler - make it run immediately 
            self.scheduler.add_job(
                func=self._run_scrape_job,
                args=[job_id, run_id, query, max_depth, config],
                id=job_id,
                replace_existing=True,
                trigger='date',  # Run immediately
                run_date=datetime.now()
            )
            
            # Track job
            with self.lock:
                self.jobs[job_id] = {
                    'run_id': run_id,
                    'query': query,
                    'start_time': datetime.utcnow(),
                    'status': 'scheduled'
                }
                
            logger.info(f"Job {job_id} scheduled in APScheduler, now waiting for execution")
            return job_id
        except Exception as e:
            logger.error(f"Error scheduling scrape job: {str(e)}")
            return None
        
    def _run_scrape_job(self, job_id: str, run_id: int, query: str, max_depth: int = 2,
                       config: Optional[Dict[str, Any]] = None):
        """
        Run a scraping job.
        
        Args:
            job_id: Job ID
            run_id: Scrape run ID
            query: Search query
            max_depth: Maximum crawl depth
            config: Optional configuration for the crawler
        """
        logger.info(f"Starting scrape job {job_id} for query: {query}")
        
        # Update job status
        with self.lock:
            if job_id in self.jobs:
                self.jobs[job_id]['status'] = 'running'
                
        # Get database session
        db = None
        try:
            db = next(get_db())
            
            # Update run status in database
            run = db.query(ScrapeRun).filter(ScrapeRun.id == run_id).first()
            if run:
                logger.info(f"Updating run status to 'running' for run_id={run_id}")
                run.status = 'running'
                run.updated_at = datetime.utcnow()
                db.commit()
                logger.info(f"Status updated: run_id={run_id}, status={run.status}")
            else:
                logger.error(f"Could not find run with ID {run_id}")
                return
                
            # Start the controller
            logger.info(f"Starting controller for job_id={job_id}")
            scrape_control.start(job_id)
            
            # If we have a config, use that
            if config:
                logger.info(f"Using provided config for job_id={job_id}")
                crawler_config = config
            else:
                # Otherwise search for top results and create config
                logger.info(f"Searching Bing for query: {query}")
                search_results = search_bing(query, num_results=5)
                logger.info(f"Found {len(search_results)} search results")
                
                # Create crawler config
                crawler_config = {
                    'start_urls': [result['url'] for result in search_results],
                    'allowed_domains': None,  # Allow any domain
                    'max_depth': max_depth,
                    'max_pages': 50,  # Reasonable limit
                    'follow_external_links': False,
                    'wait_time': 1.0,  # Be polite
                    'css_selectors': None  # No specific selectors
                }
                
                # Save the initial search results to database
                if run:
                    logger.info(f"Saving initial search results to database for run_id={run_id}")
                    for i, result in enumerate(search_results):
                        try:
                            page = ScrapedPage(
                                scrape_run_id=run_id,
                                url=result['url'],
                                title=result['title'],
                                crawl_depth=0,
                                content_text=result['snippet'],
                                page_metadata={  # Using page_metadata instead of metadata
                                    'source': 'bing_search',
                                    'position': i + 1,
                                    'site': result.get('site', '')
                                }
                            )
                            db.add(page)
                        except Exception as e:
                            logger.error(f"Error adding page to database: {str(e)}")
                    db.commit()
                    logger.info(f"Initial search results saved to database for run_id={run_id}")
            
            # Create crawler
            logger.info(f"Creating crawler for job_id={job_id}")
            crawler = Crawler(job_id, config=crawler_config, db_session=db)
            
            # Create callback to save results
            def save_page_callback(result):
                try:
                    # Create ScrapedPage record
                    page = ScrapedPage(
                        scrape_run_id=run_id,
                        url=result['url'],
                        title=result['title'],
                        crawl_depth=result['depth'],
                        content_text=result['text'],
                        content_html=result['html'],
                        page_metadata=result['metadata'],  # Using page_metadata instead of metadata
                        crawled_at=datetime.utcnow()
                    )
                    db.add(page)
                    db.flush()  # Get ID without committing
                    
                    # Create PageLink records
                    for link in result['links']:
                        link_record = PageLink(
                            page_id=page.id,
                            url=link['url'],
                            anchor_text=link['anchor_text'],
                            is_internal=link['is_internal'],
                            is_crawled=False
                        )
                        db.add(link_record)
                        
                    db.commit()
                    
                    # Update run stats
                    run = db.query(ScrapeRun).filter(ScrapeRun.id == run_id).first()
                    if run:
                        run.pages_crawled = db.query(ScrapedPage).filter(
                            ScrapedPage.scrape_run_id == run_id
                        ).count()
                        run.updated_at = datetime.utcnow()
                        db.commit()
                        
                except Exception as e:
                    logger.error(f"Error saving page: {str(e)}")
                    if db and db.is_active:
                        db.rollback()
            
            # Start crawling
            logger.info(f"Starting crawl for job_id={job_id}")
            crawler.crawl(callback=save_page_callback)
            logger.info(f"Crawl completed for job_id={job_id}")
            
            # Check final status
            status = scrape_control.get_status(job_id)
            logger.info(f"Final controller status for job_id={job_id}: {status}")
            
            # Update run in database
            run = db.query(ScrapeRun).filter(ScrapeRun.id == run_id).first()
            if run:
                if status == 'completed':
                    run.status = 'completed'
                elif status == 'stopped':
                    run.status = 'stopped'
                else:
                    run.status = 'failed'
                    
                run.completed_at = datetime.utcnow()
                run.pages_crawled = db.query(ScrapedPage).filter(
                    ScrapedPage.scrape_run_id == run_id
                ).count()
                
                db.commit()
                logger.info(f"Final database status for run_id={run_id}: {run.status}")
                
        except Exception as e:
            logger.error(f"Error in scrape job {job_id}: {str(e)}", exc_info=True)
            
            # Update run in database
            try:
                if db and db.is_active:
                    run = db.query(ScrapeRun).filter(ScrapeRun.id == run_id).first()
                    if run:
                        run.status = 'failed'
                        run.updated_at = datetime.utcnow()
                        db.commit()
                        logger.info(f"Updated run status to 'failed' after error: run_id={run_id}")
            except Exception as db_error:
                logger.error(f"Error updating run status: {str(db_error)}")
                
        finally:
            # Clean up
            try:
                scrape_control.cleanup_job(job_id)
                logger.info(f"Cleaned up job_id={job_id}")
            except Exception as e:
                logger.error(f"Error cleaning up job {job_id}: {str(e)}")
                
            # Update job status
            with self.lock:
                if job_id in self.jobs:
                    self.jobs[job_id]['status'] = 'completed'
                    self.jobs[job_id]['end_time'] = datetime.utcnow()
                    logger.info(f"Updated internal job status to 'completed': job_id={job_id}")
                    
            if db:
                try:
                    db.close()
                    logger.info(f"Closed database connection for job_id={job_id}")
                except Exception as e:
                    logger.error(f"Error closing database connection: {str(e)}")
    
    def pause_job(self, job_id: str) -> bool:
        """
        Pause a running job.
        
        Args:
            job_id: Job ID
            
        Returns:
            bool: Success
        """
        try:
            # Pause in controller
            success = scrape_control.pause(job_id)
            
            if success:
                # Update job status
                with self.lock:
                    if job_id in self.jobs:
                        self.jobs[job_id]['status'] = 'paused'
                        
                # Update run in database
                db = None
                try:
                    db = next(get_db())
                    run_id = self.jobs.get(job_id, {}).get('run_id')
                    if run_id:
                        run = db.query(ScrapeRun).filter(ScrapeRun.id == run_id).first()
                        if run:
                            run.status = 'paused'
                            run.updated_at = datetime.utcnow()
                            db.commit()
                except Exception as e:
                    logger.error(f"Error updating run status: {str(e)}")
                finally:
                    if db:
                        db.close()
                        
            return success
        except Exception as e:
            logger.error(f"Error pausing job {job_id}: {str(e)}")
            return False
        
    def resume_job(self, job_id: str) -> bool:
        """
        Resume a paused job.
        
        Args:
            job_id: Job ID
            
        Returns:
            bool: Success
        """
        try:
            # Resume in controller
            success = scrape_control.resume(job_id)
            
            if success:
                # Update job status
                with self.lock:
                    if job_id in self.jobs:
                        self.jobs[job_id]['status'] = 'running'
                        
                # Update run in database
                db = None
                try:
                    db = next(get_db())
                    run_id = self.jobs.get(job_id, {}).get('run_id')
                    if run_id:
                        run = db.query(ScrapeRun).filter(ScrapeRun.id == run_id).first()
                        if run:
                            run.status = 'running'
                            run.updated_at = datetime.utcnow()
                            db.commit()
                except Exception as e:
                    logger.error(f"Error updating run status: {str(e)}")
                finally:
                    if db:
                        db.close()
                        
            return success
        except Exception as e:
            logger.error(f"Error resuming job {job_id}: {str(e)}")
            return False
        
    def stop_job(self, job_id: str) -> bool:
        """
        Stop a job.
        
        Args:
            job_id: Job ID
            
        Returns:
            bool: Success
        """
        try:
            # Stop in controller
            success = scrape_control.stop(job_id)
            
            if success:
                # Update job status
                with self.lock:
                    if job_id in self.jobs:
                        self.jobs[job_id]['status'] = 'stopped'
                        self.jobs[job_id]['end_time'] = datetime.utcnow()
                        
                # Update run in database
                db = None
                try:
                    db = next(get_db())
                    run_id = self.jobs.get(job_id, {}).get('run_id')
                    if run_id:
                        run = db.query(ScrapeRun).filter(ScrapeRun.id == run_id).first()
                        if run:
                            run.status = 'stopped'
                            run.updated_at = datetime.utcnow()
                            run.completed_at = datetime.utcnow()
                            db.commit()
                except Exception as e:
                    logger.error(f"Error updating run status: {str(e)}")
                finally:
                    if db:
                        db.close()
                        
            return success
        except Exception as e:
            logger.error(f"Error stopping job {job_id}: {str(e)}")
            return False
        
    def get_job_status(self, job_id: str) -> str:
        """
        Get the status of a job.
        
        Args:
            job_id: Job ID
            
        Returns:
            str: Job status
        """
        try:
            with self.lock:
                if job_id in self.jobs:
                    return self.jobs[job_id]['status']
                
            return 'unknown'
        except Exception as e:
            logger.error(f"Error getting job status {job_id}: {str(e)}")
            return 'unknown'
        
    def get_all_jobs(self) -> Dict[str, Dict[str, Any]]:
        """
        Get all jobs.
        
        Returns:
            dict: Jobs dictionary
        """
        try:
            with self.lock:
                return self.jobs.copy()
        except Exception as e:
            logger.error(f"Error getting all jobs: {str(e)}")
            return {}

# Create global scheduler instance
scheduler = WebIntelScheduler()

# Helper functions

def start_scheduler():
    """Start the scheduler."""
    try:
        scheduler.start()
    except Exception as e:
        logger.error(f"Error starting scheduler: {str(e)}")
    
def shutdown_scheduler():
    """Shutdown the scheduler."""
    try:
        scheduler.shutdown()
    except Exception as e:
        logger.error(f"Error shutting down scheduler: {str(e)}")
    
def create_scrape_job(query: str, max_depth: int = 2, config: Optional[Dict[str, Any]] = None) -> int:
    """
    Create a new scrape job.
    
    Args:
        query: Search query
        max_depth: Maximum crawl depth
        config: Optional crawler configuration
        
    Returns:
        int: Scrape run ID
    """
    # Create run record
    db = None
    try:
        db = next(get_db())
        run = ScrapeRun(
            query=query,
            status='pending',
            max_depth=max_depth,
            config=config
        )
        db.add(run)
        db.commit()
        
        # Schedule the job
        scheduler.schedule_scrape_job(run.id, query, max_depth, db, config)
        
        return run.id
    except Exception as e:
        logger.error(f"Error creating scrape job: {str(e)}")
        if db and db.is_active:
            db.rollback()
        raise
    finally:
        if db:
            db.close()
        
def create_crawl_job_from_yaml(yaml_str: str) -> int:
    """
    Create a new crawl job from YAML configuration.
    
    Args:
        yaml_str: YAML configuration string
        
    Returns:
        int: Scrape run ID
    """
    try:
        # Parse YAML
        config = yaml.safe_load(yaml_str)
        
        # Extract query
        query = config.get('query', 'Custom Crawl')
        
        # Create run
        return create_scrape_job(query, config=config)
    except Exception as e:
        logger.error(f"Error creating crawl job from YAML: {str(e)}")
        raise ValueError(f"Invalid YAML configuration: {str(e)}")
        
def pause_scrape_job(run_id: int) -> bool:
    """
    Pause a scrape job.
    
    Args:
        run_id: Scrape run ID
        
    Returns:
        bool: Success
    """
    try:
        job_id = f"scrape_{run_id}"
        return scheduler.pause_job(job_id)
    except Exception as e:
        logger.error(f"Error pausing scrape job {run_id}: {str(e)}")
        return False
    
def resume_scrape_job(run_id: int) -> bool:
    """
    Resume a paused scrape job.
    
    Args:
        run_id: Scrape run ID
        
    Returns:
        bool: Success
    """
    try:
        job_id = f"scrape_{run_id}"
        return scheduler.resume_job(job_id)
    except Exception as e:
        logger.error(f"Error resuming scrape job {run_id}: {str(e)}")
        return False
    
def stop_scrape_job(run_id: int) -> bool:
    """
    Stop a scrape job.
    
    Args:
        run_id: Scrape run ID
        
    Returns:
        bool: Success
    """
    try:
        job_id = f"scrape_{run_id}"
        return scheduler.stop_job(job_id)
    except Exception as e:
        logger.error(f"Error stopping scrape job {run_id}: {str(e)}")
        return False