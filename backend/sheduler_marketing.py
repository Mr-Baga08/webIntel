"""
Extensions to the scheduler for marketing data collection.
This module adds marketing-specific job types to the WebIntel scheduler.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
import json

from .scheduler import scheduler, WebIntelScheduler
from .models import ScrapeRun
from .db.init_db import get_db
from .integration.marketing_integration import MarketingIntegration

logger = logging.getLogger(__name__)

def create_marketing_scrape_job(query: str, sources: List[str] = None, 
                             max_items_per_source: int = 5) -> int:
    """
    Create a new marketing scrape job.
    
    Args:
        query: Marketing search query
        sources: List of sources to collect from
        max_items_per_source: Maximum items per source
        
    Returns:
        int: Scrape run ID
    """
    if sources is None:
        sources = ['web', 'pdf', 'social', 'video', 'podcast', 'dataset']
    
    # Create run record
    db = next(get_db())
    try:
        # Create run
        run = ScrapeRun(
            query=f"Marketing: {query}",
            status="pending",
            max_depth=0,  # Marketing jobs don't use depth
            config={
                "marketing_query": query,
                "sources": sources,
                "max_items_per_source": max_items_per_source,
                "job_type": "marketing"  # Mark as marketing job
            }
        )
        db.add(run)
        db.commit()
        
        # Schedule the job
        job_id = f"marketing_{run.id}"
        scheduler.schedule_marketing_job(run.id, query, sources, max_items_per_source)
        
        logger.info(f"Created marketing scrape job with ID {job_id} for query: {query}")
        
        return run.id
    except Exception as e:
        logger.error(f"Error creating marketing scrape job: {str(e)}")
        if db and db.is_active:
            db.rollback()
        raise
    finally:
        if db:
            db.close()

# Extend WebIntelScheduler with marketing capabilities
def extend_scheduler(scheduler_instance: WebIntelScheduler):
    """
    Extend the WebIntelScheduler with marketing capabilities.
    
    Args:
        scheduler_instance: WebIntelScheduler instance to extend
    """
    scheduler_instance.schedule_marketing_job = schedule_marketing_job.__get__(scheduler_instance)
    scheduler_instance._run_marketing_job = _run_marketing_job.__get__(scheduler_instance)
    
    # Add _schedule_pending_marketing_jobs to _schedule_pending_jobs
    original_schedule_pending = scheduler_instance._schedule_pending_jobs
    
    def extended_schedule_pending_jobs(self):
        """Extended version of _schedule_pending_jobs that includes marketing jobs."""
        # Call original method
        original_schedule_pending(self)
        
        # Schedule pending marketing jobs
        self._schedule_pending_marketing_jobs()
    
    scheduler_instance._schedule_pending_jobs = extended_schedule_pending_jobs.__get__(scheduler_instance)
    scheduler_instance._schedule_pending_marketing_jobs = _schedule_pending_marketing_jobs.__get__(scheduler_instance)
    
    logger.info("Extended scheduler with marketing capabilities")

def schedule_marketing_job(self, run_id: int, query: str, sources: List[str], 
                         max_items_per_source: int = 5) -> str:
    """
    Schedule a new marketing job.
    
    Args:
        run_id: Scrape run ID
        query: Marketing search query
        sources: List of sources to collect from
        max_items_per_source: Maximum items per source
        
    Returns:
        str: Job ID
    """
    try:
        logger.info(f"Scheduling marketing job for query: {query}")
        
        # Create job ID
        job_id = f"marketing_{run_id}"
        
        # Add job to scheduler - make it run immediately 
        self.scheduler.add_job(
            func=self._run_marketing_job,
            args=[job_id, run_id, query, sources, max_items_per_source],
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
                'status': 'scheduled',
                'job_type': 'marketing'
            }
            
        logger.info(f"Marketing job {job_id} scheduled, now waiting for execution")
        return job_id
    except Exception as e:
        logger.error(f"Error scheduling marketing job: {str(e)}")
        return None

def _run_marketing_job(self, job_id: str, run_id: int, query: str, 
                     sources: List[str], max_items_per_source: int = 5):
    """
    Run a marketing scrape job.
    
    Args:
        job_id: Job ID
        run_id: Scrape run ID
        query: Marketing search query
        sources: List of sources to collect from
        max_items_per_source: Maximum items per source
    """
    logger.info(f"Starting marketing job {job_id} for query: {query}")
    
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
            
        # Create integration
        integration = MarketingIntegration(db_session=db)
        
        # Execute the scrape
        try:
            results = integration.execute_marketing_scrape(run_id)
            logger.info(f"Marketing scrape completed: {results}")
            
            # Update run status
            run = db.query(ScrapeRun).filter(ScrapeRun.id == run_id).first()
            if run:
                run.status = 'completed'
                run.completed_at = datetime.utcnow()
                db.commit()
        except Exception as e:
            logger.error(f"Error executing marketing scrape: {str(e)}")
            
            # Update run status
            run = db.query(ScrapeRun).filter(ScrapeRun.id == run_id).first()
            if run:
                run.status = 'failed'
                run.updated_at = datetime.utcnow()
                db.commit()
            
    except Exception as e:
        logger.error(f"Error in marketing job {job_id}: {str(e)}", exc_info=True)
        
        # Update run status
        try:
            if db and db.is_active:
                run = db.query(ScrapeRun).filter(ScrapeRun.id == run_id).first()
                if run:
                    run.status = 'failed'
                    run.updated_at = datetime.utcnow()
                    db.commit()
        except Exception as db_error:
            logger.error(f"Error updating run status: {str(db_error)}")
            
    finally:
        # Update job status
        with self.lock:
            if job_id in self.jobs:
                self.jobs[job_id]['status'] = 'completed'
                self.jobs[job_id]['end_time'] = datetime.utcnow()
                
        # Close database session
        if db:
            db.close()

def _schedule_pending_marketing_jobs(self):
    """Look for pending marketing jobs in the database and schedule them."""
    try:
        logger.info("Checking for pending marketing jobs in the database")
        db = next(get_db())
        try:
            # Find runs with job_type = marketing and status = pending
            pending_runs = db.query(ScrapeRun).filter(
                ScrapeRun.status == 'pending',
            ).all()
            
            marketing_runs = []
            for run in pending_runs:
                if run.config and run.config.get('job_type') == 'marketing':
                    marketing_runs.append(run)
            
            logger.info(f"Found {len(marketing_runs)} pending marketing jobs")
            
            for run in marketing_runs:
                logger.info(f"Scheduling pending marketing job for run_id={run.id}")
                
                # Get configuration
                config = run.config or {}
                query = config.get('marketing_query', run.query)
                sources = config.get('sources', ['web', 'pdf', 'social', 'video', 'podcast', 'dataset'])
                max_items_per_source = config.get('max_items_per_source', 5)
                
                # Schedule job
                self.schedule_marketing_job(run.id, query, sources, max_items_per_source)
                
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Error scheduling pending marketing jobs: {str(e)}")

# Extend the scheduler when this module is imported
extend_scheduler(scheduler)