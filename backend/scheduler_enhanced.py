"""
Extensions to the scheduler for enhanced content collection.
This module adds general content collection job types to the WebIntel scheduler.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
import json

from .scheduler import scheduler, WebIntelScheduler
from .models import ScrapeRun
from .db.init_db import get_db
from .integration.enhanced_content_integration import EnhancedContentIntegration

logger = logging.getLogger(__name__)

def create_enhanced_content_job(query: str, domain_expertise: Optional[str] = None,
                             sources: List[str] = None, 
                             max_items_per_source: int = 5) -> int:
    """
    Create a new enhanced content scrape job.
    
    Args:
        query: Content search query
        domain_expertise: Optional domain expertise for specialized analysis
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
        # Build run name
        run_name = query
        if domain_expertise:
            run_name = f"{domain_expertise.capitalize()}: {query}"
        
        # Create run
        run = ScrapeRun(
            query=run_name,
            status="pending",
            max_depth=0,  # Enhanced content jobs don't use depth
            config={
                "content_query": query,
                "domain_expertise": domain_expertise,
                "sources": sources,
                "max_items_per_source": max_items_per_source,
                "job_type": "enhanced_content"  # Mark as enhanced content job
            }
        )
        db.add(run)
        db.commit()
        
        # Schedule the job
        job_id = f"enhanced_{run.id}"
        scheduler.schedule_enhanced_job(run.id, query, domain_expertise, sources, max_items_per_source)
        
        logger.info(f"Created enhanced content job with ID {job_id} for query: {query}")
        
        return run.id
    except Exception as e:
        logger.error(f"Error creating enhanced content job: {str(e)}")
        if db and db.is_active:
            db.rollback()
        raise
    finally:
        if db:
            db.close()

# Extend WebIntelScheduler with enhanced content capabilities
def extend_scheduler(scheduler_instance: WebIntelScheduler):
    """
    Extend the WebIntelScheduler with enhanced content capabilities.
    
    Args:
        scheduler_instance: WebIntelScheduler instance to extend
    """
    scheduler_instance.schedule_enhanced_job = schedule_enhanced_job.__get__(scheduler_instance)
    scheduler_instance._run_enhanced_job = _run_enhanced_job.__get__(scheduler_instance)
    
    # Add _schedule_pending_enhanced_jobs to _schedule_pending_jobs
    original_schedule_pending = scheduler_instance._schedule_pending_jobs
    
    def extended_schedule_pending_jobs(self):
        """Extended version of _schedule_pending_jobs that includes enhanced content jobs."""
        # Call original method
        original_schedule_pending(self)
        
        # Schedule pending enhanced content jobs
        self._schedule_pending_enhanced_jobs()
    
    scheduler_instance._schedule_pending_jobs = extended_schedule_pending_jobs.__get__(scheduler_instance)
    scheduler_instance._schedule_pending_enhanced_jobs = _schedule_pending_enhanced_jobs.__get__(scheduler_instance)
    
    logger.info("Extended scheduler with enhanced content capabilities")

def schedule_enhanced_job(self, run_id: int, query: str, domain_expertise: Optional[str],
                        sources: List[str], max_items_per_source: int = 5) -> str:
    """
    Schedule a new enhanced content job.
    
    Args:
        run_id: Scrape run ID
        query: Content search query
        domain_expertise: Optional domain expertise 
        sources: List of sources to collect from
        max_items_per_source: Maximum items per source
        
    Returns:
        str: Job ID
    """
    try:
        logger.info(f"Scheduling enhanced content job for query: {query}")
        
        # Create job ID
        job_id = f"enhanced_{run_id}"
        
        # Add job to scheduler - make it run immediately 
        self.scheduler.add_job(
            func=self._run_enhanced_job,
            args=[job_id, run_id, query, domain_expertise, sources, max_items_per_source],
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
                'domain_expertise': domain_expertise,
                'start_time': datetime.utcnow(),
                'status': 'scheduled',
                'job_type': 'enhanced_content'
            }
            
        logger.info(f"Enhanced content job {job_id} scheduled, now waiting for execution")
        return job_id
    except Exception as e:
        logger.error(f"Error scheduling enhanced content job: {str(e)}")
        return None

def _run_enhanced_job(self, job_id: str, run_id: int, query: str, domain_expertise: Optional[str], 
                    sources: List[str], max_items_per_source: int = 5):
    """
    Run an enhanced content scrape job.
    
    Args:
        job_id: Job ID
        run_id: Scrape run ID
        query: Content search query
        domain_expertise: Optional domain expertise
        sources: List of sources to collect from
        max_items_per_source: Maximum items per source
    """
    logger.info(f"Starting enhanced content job {job_id} for query: {query}")
    
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
        integration = EnhancedContentIntegration(db_session=db, domain_expertise=domain_expertise)
        
        # Execute the scrape
        try:
            results = integration.execute_content_scrape(run_id)
            logger.info(f"Enhanced content scrape completed: {results}")
            
            # Update run status
            run = db.query(ScrapeRun).filter(ScrapeRun.id == run_id).first()
            if run:
                run.status = 'completed'
                run.completed_at = datetime.utcnow()
                db.commit()
        except Exception as e:
            logger.error(f"Error executing enhanced content scrape: {str(e)}")
            
            # Update run status
            run = db.query(ScrapeRun).filter(ScrapeRun.id == run_id).first()
            if run:
                run.status = 'failed'
                run.updated_at = datetime.utcnow()
                db.commit()
            
    except Exception as e:
        logger.error(f"Error in enhanced content job {job_id}: {str(e)}", exc_info=True)
        
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

def _schedule_pending_enhanced_jobs(self):
    """Look for pending enhanced content jobs in the database and schedule them."""
    try:
        logger.info("Checking for pending enhanced content jobs in the database")
        db = next(get_db())
        try:
            # Find runs with job_type = enhanced_content and status = pending
            pending_runs = db.query(ScrapeRun).filter(
                ScrapeRun.status == 'pending',
            ).all()
            
            enhanced_runs = []
            for run in pending_runs:
                if run.config and run.config.get('job_type') == 'enhanced_content':
                    enhanced_runs.append(run)
            
            logger.info(f"Found {len(enhanced_runs)} pending enhanced content jobs")
            
            for run in enhanced_runs:
                logger.info(f"Scheduling pending enhanced content job for run_id={run.id}")
                
                # Get configuration
                config = run.config or {}
                query = config.get('content_query', run.query)
                domain_expertise = config.get('domain_expertise')
                sources = config.get('sources', ['web', 'pdf', 'social', 'video', 'podcast', 'dataset'])
                max_items_per_source = config.get('max_items_per_source', 5)
                
                # Schedule job
                self.schedule_enhanced_job(run.id, query, domain_expertise, sources, max_items_per_source)
                
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Error scheduling pending enhanced content jobs: {str(e)}")

# Extend the scheduler when this module is imported
extend_scheduler(scheduler)