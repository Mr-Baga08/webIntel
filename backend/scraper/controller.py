import logging
import time
import threading
from threading import Lock
from typing import Dict, Optional

logger = logging.getLogger(__name__)

class ScraperControl:
    """
    Thread-safe controller for managing the state of scraping operations.
    Provides pause/resume/abort functionality for individual scrape jobs.
    """
    
    def __init__(self):
        self.jobs = {}  # Dictionary to track all running scrape jobs
        self.lock = Lock()
        
    def register_job(self, job_id):
        """Register a new scraping job with the controller."""
        with self.lock:
            self.jobs[job_id] = {
                'running': False,
                'paused': False,
                'last_activity': time.time(),
                'stats': {
                    'pages_crawled': 0,
                    'bytes_downloaded': 0,
                    'start_time': None,
                    'end_time': None
                }
            }
        return job_id
            
    def start(self, job_id):
        """Start or resume a scraping job."""
        try:
            with self.lock:
                if job_id not in self.jobs:
                    self.register_job(job_id)
                    
                self.jobs[job_id]['running'] = True
                self.jobs[job_id]['paused'] = False
                self.jobs[job_id]['last_activity'] = time.time()
                
                if self.jobs[job_id]['stats']['start_time'] is None:
                    self.jobs[job_id]['stats']['start_time'] = time.time()
                    
            logger.info(f"Job {job_id} started")
        except Exception as e:
            logger.error(f"Error starting job {job_id}: {str(e)}")
                
    def pause(self, job_id):
        """Pause a scraping job."""
        try:
            with self.lock:
                if job_id not in self.jobs:
                    logger.warning(f"Attempted to pause non-existent job {job_id}")
                    return False
                    
                self.jobs[job_id]['paused'] = True
                self.jobs[job_id]['last_activity'] = time.time()
                
            logger.info(f"Job {job_id} paused")
            return True
        except Exception as e:
            logger.error(f"Error pausing job {job_id}: {str(e)}")
            return False
            
    def resume(self, job_id):
        """Resume a paused scraping job."""
        try:
            with self.lock:
                if job_id not in self.jobs:
                    logger.warning(f"Attempted to resume non-existent job {job_id}")
                    return False
                    
                self.jobs[job_id]['paused'] = False
                self.jobs[job_id]['last_activity'] = time.time()
                
            logger.info(f"Job {job_id} resumed")
            return True
        except Exception as e:
            logger.error(f"Error resuming job {job_id}: {str(e)}")
            return False
            
    def stop(self, job_id):
        """Stop/abort a scraping job."""
        try:
            with self.lock:
                if job_id not in self.jobs:
                    logger.warning(f"Attempted to stop non-existent job {job_id}")
                    return False
                    
                self.jobs[job_id]['running'] = False
                self.jobs[job_id]['paused'] = False
                self.jobs[job_id]['last_activity'] = time.time()
                self.jobs[job_id]['stats']['end_time'] = time.time()
                
            logger.info(f"Job {job_id} stopped")
            return True
        except Exception as e:
            logger.error(f"Error stopping job {job_id}: {str(e)}")
            return False
            
    def complete(self, job_id):
        """Mark a job as completed successfully."""
        try:
            with self.lock:
                if job_id not in self.jobs:
                    logger.warning(f"Attempted to complete non-existent job {job_id}")
                    return False
                    
                self.jobs[job_id]['running'] = False
                self.jobs[job_id]['paused'] = False
                self.jobs[job_id]['last_activity'] = time.time()
                self.jobs[job_id]['stats']['end_time'] = time.time()
                
            logger.info(f"Job {job_id} completed")
            return True
        except Exception as e:
            logger.error(f"Error marking job {job_id} as complete: {str(e)}")
            return False
            
    def should_continue(self, job_id):
        """Check if a job should continue running."""
        try:
            with self.lock:
                if job_id not in self.jobs:
                    logger.warning(f"Checked status of non-existent job {job_id}")
                    return False
                    
                return self.jobs[job_id]['running']
        except Exception as e:
            logger.error(f"Error checking if job {job_id} should continue: {str(e)}")
            return False
            
    def is_paused(self, job_id):
        """Check if a job is currently paused."""
        try:
            with self.lock:
                if job_id not in self.jobs:
                    logger.warning(f"Checked pause status of non-existent job {job_id}")
                    return False
                    
                return self.jobs[job_id]['paused']
        except Exception as e:
            logger.error(f"Error checking if job {job_id} is paused: {str(e)}")
            return False
    
    def update_stats(self, job_id, pages_crawled=None, bytes_downloaded=None):
        """Update job statistics."""
        try:
            with self.lock:
                if job_id not in self.jobs:
                    logger.warning(f"Attempted to update stats for non-existent job {job_id}")
                    return False
                    
                if pages_crawled is not None:
                    self.jobs[job_id]['stats']['pages_crawled'] = pages_crawled
                    
                if bytes_downloaded is not None:
                    self.jobs[job_id]['stats']['bytes_downloaded'] = bytes_downloaded
                    
                self.jobs[job_id]['last_activity'] = time.time()
                
            return True
        except Exception as e:
            logger.error(f"Error updating stats for job {job_id}: {str(e)}")
            return False
    
    def get_status(self, job_id):
        """Get the current status of a job."""
        try:
            with self.lock:
                if job_id not in self.jobs:
                    return None
                    
                job = self.jobs[job_id]
                
                if not job['running']:
                    if job['stats']['end_time'] is not None:
                        return "completed"
                    return "stopped"
                elif job['paused']:
                    return "paused"
                else:
                    return "running"
        except Exception as e:
            logger.error(f"Error getting status for job {job_id}: {str(e)}")
            return None
    
    def get_stats(self, job_id):
        """Get the current statistics for a job."""
        try:
            with self.lock:
                if job_id not in self.jobs:
                    return None
                    
                return self.jobs[job_id]['stats']
        except Exception as e:
            logger.error(f"Error getting stats for job {job_id}: {str(e)}")
            return None
    
    def cleanup_job(self, job_id):
        """Remove a job from the controller once it's no longer needed."""
        try:
            with self.lock:
                if job_id in self.jobs:
                    del self.jobs[job_id]
                    logger.info(f"Job {job_id} removed from controller")
                    return True
                return False
        except Exception as e:
            logger.error(f"Error cleaning up job {job_id}: {str(e)}")
            return False

# Create a global instance of the scraper controller
scrape_control = ScraperControl()