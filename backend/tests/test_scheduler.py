import pytest
from unittest.mock import patch, MagicMock, call
from datetime import datetime

from backend.scheduler import WebIntelScheduler, create_scrape_job, pause_scrape_job, resume_scrape_job, stop_scrape_job, create_crawl_job_from_yaml
from backend.models import ScrapeRun, ScrapedPage

class TestWebIntelScheduler:
    """Tests for the WebIntelScheduler class."""
    
    def test_scheduler_init(self):
        """Test scheduler initialization."""
        scheduler = WebIntelScheduler(max_workers=3)
        
        # Verify properties
        assert scheduler.scheduler is not None
        assert len(scheduler.jobs) == 0
        assert scheduler.lock is not None
    
    @patch('backend.scheduler.BackgroundScheduler')
    def test_start_shutdown(self, mock_scheduler_class):
        """Test starting and shutting down the scheduler."""
        # Mock scheduler
        mock_scheduler = MagicMock()
        mock_scheduler_class.return_value = mock_scheduler
        
        # Create and start scheduler
        scheduler = WebIntelScheduler()
        scheduler.start()
        
        # Verify start was called
        mock_scheduler.start.assert_called_once()
        
        # Shutdown scheduler
        scheduler.shutdown()
        
        # Verify shutdown was called
        mock_scheduler.shutdown.assert_called_once()
    
    @patch('backend.scheduler.BackgroundScheduler')
    def test_schedule_scrape_job(self, mock_scheduler_class):
        """Test scheduling a scrape job."""
        # Mock scheduler
        mock_scheduler = MagicMock()
        mock_scheduler_class.return_value = mock_scheduler
        
        # Create scheduler
        scheduler = WebIntelScheduler()
        
        # Mock scrape_control
        with patch('backend.scheduler.scrape_control') as mock_control:
            # Schedule job
            job_id = scheduler.schedule_scrape_job(1, "test query", max_depth=2)
            
            # Verify job ID
            assert job_id == "scrape_1"
            
            # Verify scrape_control call
            mock_control.register_job.assert_called_once_with("scrape_1")
            
            # Verify scheduler add_job call
            mock_scheduler.add_job.assert_called_once()
            
            # Verify job tracking
            assert "scrape_1" in scheduler.jobs
            assert scheduler.jobs["scrape_1"]["run_id"] == 1
            assert scheduler.jobs["scrape_1"]["query"] == "test query"
            assert scheduler.jobs["scrape_1"]["status"] == "scheduled"
    
    @patch('backend.scheduler.get_db')
    @patch('backend.scheduler.BackgroundScheduler')
    def test_run_scrape_job(self, mock_scheduler_class, mock_get_db):
        """Test running a scrape job."""
        # Mock database session
        mock_session = MagicMock()
        mock_db = MagicMock()
        mock_get_db.return_value.__next__.return_value = mock_db
        
        # Mock scheduler
        mock_scheduler = MagicMock()
        mock_scheduler_class.return_value = mock_scheduler
        
        # Mock ScrapeRun query
        mock_run = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_run
        
        # Create scheduler
        scheduler = WebIntelScheduler()
        
        # Register job
        job_id = "scrape_1"
        run_id = 1
        query = "test query"
        scheduler.jobs[job_id] = {
            'run_id': run_id,
            'query': query,
            'start_time': datetime.utcnow(),
            'status': 'scheduled'
        }
        
        # Mock search results
        mock_search_results = [
            {'url': 'https://example.com/1', 'title': 'Example 1', 'snippet': 'Test snippet 1'},
            {'url': 'https://example.com/2', 'title': 'Example 2', 'snippet': 'Test snippet 2'}
        ]
        
        # Mock crawler
        mock_crawler = MagicMock()
        mock_crawler.crawl.return_value = [
            {'url': 'https://example.com/1', 'title': 'Example 1', 'text': 'Test content 1'},
            {'url': 'https://example.com/2', 'title': 'Example 2', 'text': 'Test content 2'}
        ]
        
        # Run with mocks for dependencies
        with patch('backend.scheduler.search_bing', return_value=mock_search_results) as mock_search, \
             patch('backend.scheduler.Crawler', return_value=mock_crawler) as mock_crawler_class, \
             patch('backend.scheduler.scrape_control') as mock_control:
            
            # Set up scrape_control behavior
            mock_control.get_status.return_value = "completed"
            
            # Run the job
            scheduler._run_scrape_job(job_id, run_id, query, max_depth=2)
            
            # Verify run status updates
            assert mock_run.status == "completed"
            assert mock_run.completed_at is not None
            
            # Verify search was called
            mock_search.assert_called_once_with(query, num_results=5)
            
            # Verify crawler was created and run
            mock_crawler_class.assert_called_once()
            mock_crawler.crawl.assert_called_once()
            
            # Verify scrape_control calls
            mock_control.start.assert_called_once_with(job_id)
            mock_control.get_status.assert_called_with(job_id)
            
            # Verify job status update
            assert scheduler.jobs[job_id]['status'] == "completed"
            assert 'end_time' in scheduler.jobs[job_id]
    
    @patch('backend.scheduler.get_db')
    @patch('backend.scheduler.BackgroundScheduler')
    def test_job_control_actions(self, mock_scheduler_class, mock_get_db):
        """Test job control actions (pause, resume, stop)."""
        # Mock database session
        mock_session = MagicMock()
        mock_db = MagicMock()
        mock_get_db.return_value.__next__.return_value = mock_db
        
        # Mock scheduler
        mock_scheduler = MagicMock()
        mock_scheduler_class.return_value = mock_scheduler
        
        # Mock ScrapeRun query
        mock_run = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_run
        
        # Create scheduler
        scheduler = WebIntelScheduler()
        
        # Register job
        job_id = "scrape_1"
        run_id = 1
        scheduler.jobs[job_id] = {
            'run_id': run_id,
            'query': 'test query',
            'start_time': datetime.utcnow(),
            'status': 'running'
        }
        
        # Test pause_job
        with patch('backend.scheduler.scrape_control') as mock_control:
            mock_control.pause.return_value = True
            
            result = scheduler.pause_job(job_id)
            
            assert result == True
            mock_control.pause.assert_called_once_with(job_id)
            assert scheduler.jobs[job_id]['status'] == 'paused'
            assert mock_run.status == 'paused'
        
        # Test resume_job
        with patch('backend.scheduler.scrape_control') as mock_control:
            mock_control.resume.return_value = True
            
            result = scheduler.resume_job(job_id)
            
            assert result == True
            mock_control.resume.assert_called_once_with(job_id)
            assert scheduler.jobs[job_id]['status'] == 'running'
            assert mock_run.status == 'running'
        
        # Test stop_job
        with patch('backend.scheduler.scrape_control') as mock_control:
            mock_control.stop.return_value = True
            
            result = scheduler.stop_job(job_id)
            
            assert result == True
            mock_control.stop.assert_called_once_with(job_id)
            assert scheduler.jobs[job_id]['status'] == 'stopped'
            assert mock_run.status == 'stopped'
            assert 'end_time' in scheduler.jobs[job_id]
            assert mock_run.completed_at is not None


@patch('backend.scheduler.get_db')
def test_create_scrape_job(mock_get_db):
    """Test the create_scrape_job helper function."""
    # Mock database session
    mock_db = MagicMock()
    mock_get_db.return_value.__next__.return_value = mock_db
    
    # Mock ScrapeRun
    mock_run = MagicMock()
    mock_run.id = 1
    mock_db.add.side_effect = lambda run: setattr(run, 'id', 1)
    
    # Mock scheduler
    with patch('backend.scheduler.scheduler') as mock_scheduler:
        # Call helper function
        run_id = create_scrape_job("test query", max_depth=2)
        
        # Verify run_id
        assert run_id == 1
        
        # Verify ScrapeRun creation
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()
        
        # Verify scheduler call
        mock_scheduler.schedule_scrape_job.assert_called_once_with(1, "test query", 2, mock_db, None)


@patch('backend.scheduler.yaml.safe_load')
@patch('backend.scheduler.create_scrape_job')
def test_create_crawl_job_from_yaml(mock_create_job, mock_yaml_load):
    """Test the create_crawl_job_from_yaml helper function."""
    # Mock YAML parsing
    mock_config = {
        'query': 'yaml query',
        'start_urls': ['https://example.com'],
        'max_depth': 3
    }
    mock_yaml_load.return_value = mock_config
    
    # Mock create_scrape_job
    mock_create_job.return_value = 1
    
    # Call helper function
    run_id = create_crawl_job_from_yaml("yaml config string")
    
    # Verify
    assert run_id == 1
    mock_yaml_load.assert_called_once_with("yaml config string")
    mock_create_job.assert_called_once_with('yaml query', config=mock_config)
    
    # Test error handling
    mock_yaml_load.side_effect = Exception("YAML error")
    
    with pytest.raises(ValueError) as e:
        create_crawl_job_from_yaml("invalid yaml")
        
    assert "Invalid YAML configuration" in str(e)


@patch('backend.scheduler.scheduler')
def test_job_control_helpers(mock_scheduler):
    """Test job control helper functions."""
    # Set up mock return values
    mock_scheduler.pause_job.return_value = True
    mock_scheduler.resume_job.return_value = True
    mock_scheduler.stop_job.return_value = True
    
    # Test pause_scrape_job
    result = pause_scrape_job(1)
    assert result == True
    mock_scheduler.pause_job.assert_called_once_with("scrape_1")
    
    # Test resume_scrape_job
    result = resume_scrape_job(1)
    assert result == True
    mock_scheduler.resume_job.assert_called_once_with("scrape_1")
    
    # Test stop_scrape_job
    result = stop_scrape_job(1)
    assert result == True
    mock_scheduler.stop_job.assert_called_once_with("scrape_1")


if __name__ == "__main__":
    pytest.main()