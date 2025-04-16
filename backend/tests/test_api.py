import pytest
import json
from unittest.mock import patch, MagicMock
from datetime import datetime

from backend.api.endpoints import api_bp
from backend.models import ScrapeRun, ScrapedPage, PageLink

# Fixture for Flask test client
@pytest.fixture
def client():
    from flask import Flask
    app = Flask(__name__)
    app.config['TESTING'] = True
    app.register_blueprint(api_bp)
    
    # Disable rate limiting for tests
    with patch('backend.api.endpoints.limiter'):
        with app.test_client() as client:
            yield client

class TestApiEndpoints:
    """Tests for the API endpoints."""
    
    @patch('backend.api.endpoints.get_db')
    def test_get_runs(self, mock_get_db, client):
        """Test the GET /runs endpoint."""
        # Mock database session
        mock_db = MagicMock()
        mock_get_db.return_value.__next__.return_value = mock_db
        
        # Mock runs
        mock_runs = [
            MagicMock(
                id=1,
                query="test query 1",
                status="completed",
                created_at=datetime(2023, 1, 1),
                completed_at=datetime(2023, 1, 2),
                pages_crawled=10,
                pages_total=10
            ),
            MagicMock(
                id=2,
                query="test query 2",
                status="running",
                created_at=datetime(2023, 1, 3),
                completed_at=None,
                pages_crawled=5,
                pages_total=20
            )
        ]
        
        # Set up query chain mocks
        mock_db.query.return_value.order_by.return_value.limit.return_value.offset.return_value.all.return_value = mock_runs
        mock_db.query.return_value.count.return_value = 2
        
        # Make request
        response = client.get('/api/runs')
        
        # Verify response
        assert response.status_code == 200
        data = json.loads(response.data)
        
        # Verify data structure
        assert 'runs' in data
        assert 'total' in data
        assert 'limit' in data
        assert 'offset' in data
        
        # Verify runs data
        assert len(data['runs']) == 2
        assert data['runs'][0]['id'] == 1
        assert data['runs'][0]['query'] == "test query 1"
        assert data['runs'][0]['status'] == "completed"
        assert data['runs'][1]['id'] == 2
        assert data['runs'][1]['status'] == "running"
        
        # Verify count
        assert data['total'] == 2
    
    @patch('backend.api.endpoints.get_db')
    def test_get_run(self, mock_get_db, client):
        """Test the GET /runs/{id} endpoint."""
        # Mock database session
        mock_db = MagicMock()
        mock_get_db.return_value.__next__.return_value = mock_db
        
        # Mock run
        mock_run = MagicMock(
            id=1,
            query="test query",
            status="completed",
            created_at=datetime(2023, 1, 1),
            updated_at=datetime(2023, 1, 1, 12, 0),
            completed_at=datetime(2023, 1, 2),
            max_depth=2,
            pages_crawled=10,
            pages_total=10,
            config={"start_urls": ["https://example.com"]}
        )
        
        # Set up query chain mocks
        mock_db.query.return_value.filter.return_value.first.return_value = mock_run
        mock_db.query.return_value.filter.return_value.count.return_value = 10
        
        # Make request
        response = client.get('/api/runs/1')
        
        # Verify response
        assert response.status_code == 200
        data = json.loads(response.data)
        
        # Verify data
        assert data['id'] == 1
        assert data['query'] == "test query"
        assert data['status'] == "completed"
        assert data['max_depth'] == 2
        assert data['pages_crawled'] == 10
        assert data['pages_total'] == 10
        assert data['config'] == {"start_urls": ["https://example.com"]}
        
        # Test not found
        mock_db.query.return_value.filter.return_value.first.return_value = None
        
        response = client.get('/api/runs/999')
        assert response.status_code == 404
    
    @patch('backend.api.endpoints.get_db')
    def test_get_run_pages(self, mock_get_db, client):
        """Test the GET /runs/{id}/pages endpoint."""
        # Mock database session
        mock_db = MagicMock()
        mock_get_db.return_value.__next__.return_value = mock_db
        
        # Mock run
        mock_run = MagicMock(id=1, query="test query")
        
        # Mock pages
        mock_pages = [
            MagicMock(
                id=1,
                url="https://example.com/1",
                title="Page 1",
                crawl_depth=0,
                crawled_at=datetime(2023, 1, 1),
                relevance_score=0.9,
                embedding_id="embed1",
                content_text="Example content 1",
                structured_data={"key": "value1"}
            ),
            MagicMock(
                id=2,
                url="https://example.com/2",
                title="Page 2",
                crawl_depth=1,
                crawled_at=datetime(2023, 1, 2),
                relevance_score=0.8,
                embedding_id="embed2",
                content_text="Example content 2",
                structured_data=None
            )
        ]
        
        # Set up query chain mocks
        mock_db.query.return_value.filter.return_value.first.return_value = mock_run
        mock_db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.offset.return_value.all.return_value = mock_pages
        mock_db.query.return_value.filter.return_value.count.return_value = 2
        
        # Make request
        response = client.get('/api/runs/1/pages')
        
        # Verify response
        assert response.status_code == 200
        data = json.loads(response.data)
        
        # Verify data structure
        assert 'pages' in data
        assert 'total' in data
        assert 'limit' in data
        assert 'offset' in data
        
        # Verify pages data
        assert len(data['pages']) == 2
        assert data['pages'][0]['id'] == 1
        assert data['pages'][0]['url'] == "https://example.com/1"
        assert data['pages'][0]['title'] == "Page 1"
        assert data['pages'][0]['relevance_score'] == 0.9
        assert 'snippet' in data['pages'][0]  # Should include snippet
        assert data['pages'][1]['id'] == 2
        assert data['pages'][1]['has_structured_data'] == False
        
        # Test run not found
        mock_db.query.return_value.filter.return_value.first.return_value = None
        
        response = client.get('/api/runs/999/pages')
        assert response.status_code == 404
    
    @patch('backend.api.endpoints.get_db')
    def test_get_page(self, mock_get_db, client):
        """Test the GET /pages/{id} endpoint."""
        # Mock database session
        mock_db = MagicMock()
        mock_get_db.return_value.__next__.return_value = mock_db
        
        # Mock page
        mock_page = MagicMock(
            id=1,
            scrape_run_id=1,
            url="https://example.com",
            title="Example Page",
            crawl_depth=0,
            content_text="Example content",
            content_html="<html><body>Example content</body></html>",
            crawled_at=datetime(2023, 1, 1),
            page_metadata={"author": "Test Author"},
            relevance_score=0.95,
            embedding_id="embed1",
            structured_data={"key": "value"}
        )
        
        # Mock links
        mock_links = [
            MagicMock(
                page_id=1,
                url="https://example.com/link1",
                anchor_text="Link 1",
                is_internal=True,
                is_crawled=True
            ),
            MagicMock(
                page_id=1,
                url="https://external.com/link",
                anchor_text="External Link",
                is_internal=False,
                is_crawled=False
            )
        ]
        
        # Set up query chain mocks
        mock_db.query.return_value.filter.return_value.first.return_value = mock_page
        mock_db.query.return_value.filter.return_value.all.return_value = mock_links
        
        # Test without HTML or links
        response = client.get('/api/pages/1')
        
        # Verify response
        assert response.status_code == 200
        data = json.loads(response.data)
        
        # Verify page data
        assert data['id'] == 1
        assert data['scrape_run_id'] == 1
        assert data['url'] == "https://example.com"
        assert data['title'] == "Example Page"
        assert data['content_text'] == "Example content"
        assert 'content_html' not in data
        assert 'links' not in data
        assert data['metadata'] == {"author": "Test Author"}
        assert data['relevance_score'] == 0.95
        assert data['structured_data'] == {"key": "value"}
        
        # Test with HTML and links
        response = client.get('/api/pages/1?include_html=true&include_links=true')
        
        # Verify response
        assert response.status_code == 200
        data = json.loads(response.data)
        
        # Verify additional data
        assert 'content_html' in data
        assert data['content_html'] == "<html><body>Example content</body></html>"
        assert 'links' in data
        assert len(data['links']) == 2
        assert data['links'][0]['url'] == "https://example.com/link1"
        assert data['links'][0]['is_internal'] == True
        assert data['links'][1]['url'] == "https://external.com/link"
        assert data['links'][1]['is_internal'] == False
        
        # Test not found
        mock_db.query.return_value.filter.return_value.first.return_value = None
        
        response = client.get('/api/pages/999')
        assert response.status_code == 404
    
    @patch('backend.api.endpoints.create_scrape_job')
    def test_create_run_with_query(self, mock_create_job, client):
        """Test the POST /runs endpoint with query parameter."""
        # Mock create_scrape_job
        mock_create_job.return_value = 1
        
        # Make request
        response = client.post(
            '/api/runs',
            json={'query': 'test query', 'max_depth': 2}
        )
        
        # Verify response
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['id'] == 1
        
        # Verify create_scrape_job call
        mock_create_job.assert_called_once_with('test query', 2)
        
        # Test validation
        response = client.post(
            '/api/runs',
            json={'max_depth': 2}  # Missing query
        )
        
        assert response.status_code == 400
        
        response = client.post(
            '/api/runs',
            json={'query': 'test', 'max_depth': 10}  # Invalid max_depth
        )
        
        assert response.status_code == 400
    
    @patch('backend.api.endpoints.create_crawl_job_from_yaml')
    def test_create_run_with_yaml(self, mock_create_job, client):
        """Test the POST /runs endpoint with YAML configuration."""
        # Mock create_crawl_job_from_yaml
        mock_create_job.return_value = 1
        
        # Make request
        response = client.post(
            '/api/runs',
            json={'yaml_config': 'start_urls:\n  - https://example.com'}
        )
        
        # Verify response
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['id'] == 1
        
        # Verify create_crawl_job_from_yaml call
        mock_create_job.assert_called_once_with('start_urls:\n  - https://example.com')
        
        # Test validation error
        mock_create_job.side_effect = ValueError("Invalid YAML")
        
        response = client.post(
            '/api/runs',
            json={'yaml_config': 'invalid: - yaml'}
        )
        
        assert response.status_code == 400
    
    @patch('backend.api.endpoints.pause_scrape_job')
    def test_pause_run(self, mock_pause_job, client):
        """Test the POST /runs/{id}/pause endpoint."""
        # Mock pause_scrape_job
        mock_pause_job.return_value = True
        
        # Make request
        response = client.post('/api/runs/1/pause')
        
        # Verify response
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['status'] == 'paused'
        
        # Verify pause_scrape_job call
        mock_pause_job.assert_called_once_with(1)
        
        # Test failure
        mock_pause_job.return_value = False
        
        response = client.post('/api/runs/1/pause')
        assert response.status_code == 400
    
    @patch('backend.api.endpoints.resume_scrape_job')
    def test_resume_run(self, mock_resume_job, client):
        """Test the POST /runs/{id}/resume endpoint."""
        # Mock resume_scrape_job
        mock_resume_job.return_value = True
        
        # Make request
        response = client.post('/api/runs/1/resume')
        
        # Verify response
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['status'] == 'running'
        
        # Verify resume_scrape_job call
        mock_resume_job.assert_called_once_with(1)
        
        # Test failure
        mock_resume_job.return_value = False
        
        response = client.post('/api/runs/1/resume')
        assert response.status_code == 400
    
    @patch('backend.api.endpoints.stop_scrape_job')
    def test_stop_run(self, mock_stop_job, client):
        """Test the POST /runs/{id}/stop endpoint."""
        # Mock stop_scrape_job
        mock_stop_job.return_value = True
        
        # Make request
        response = client.post('/api/runs/1/stop')
        
        # Verify response
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['status'] == 'stopped'
        
        # Verify stop_scrape_job call
        mock_stop_job.assert_called_once_with(1)
        
        # Test failure
        mock_stop_job.return_value = False
        
        response = client.post('/api/runs/1/stop')
        assert response.status_code == 400
    
    @patch('backend.api.endpoints.search_bing')
    def test_search(self, mock_search, client):
        """Test the GET /search endpoint."""
        # Mock search_bing
        mock_search.return_value = [
            {'title': 'Result 1', 'url': 'https://example.com/1', 'snippet': 'Snippet 1'},
            {'title': 'Result 2', 'url': 'https://example.com/2', 'snippet': 'Snippet 2'}
        ]
        
        # Make request
        response = client.get('/api/search?q=test%20query&limit=2')
        
        # Verify response
        assert response.status_code == 200
        data = json.loads(response.data)
        
        # Verify data
        assert data['query'] == 'test query'
        assert len(data['results']) == 2
        assert data['results'][0]['title'] == 'Result 1'
        assert data['results'][1]['url'] == 'https://example.com/2'
        
        # Verify search_bing call
        mock_search.assert_called_once_with('test query', num_results=2)
        
        # Test validation
        response = client.get('/api/search')  # Missing query
        assert response.status_code == 400
        
        response = client.get('/api/search?q=test&limit=50')  # Invalid limit
        assert response.status_code == 400
    
    @patch('backend.api.endpoints.get_vector_store')
    def test_vector_search(self, mock_get_vector_store, client):
        """Test the POST /vector-search endpoint."""
        # Mock vector store
        mock_vector_store = MagicMock()
        mock_get_vector_store.return_value = mock_vector_store
        
        # Mock search results
        mock_vector_store.search.return_value = [
            {'doc_id': 'page1', 'score': 0.95, 'metadata': {'run_id': 1, 'title': 'Page 1'}},
            {'doc_id': 'page2', 'score': 0.85, 'metadata': {'run_id': 1, 'title': 'Page 2'}}
        ]
        
        # Make request
        response = client.post(
            '/api/vector-search',
            json={'query': 'test query', 'run_id': 1, 'limit': 2}
        )
        
        # Verify response
        assert response.status_code == 200
        data = json.loads(response.data)
        
        # Verify data
        assert data['query'] == 'test query'
        assert len(data['results']) == 2
        assert data['results'][0]['doc_id'] == 'page1'
        assert data['results'][0]['score'] == 0.95
        
        # Verify vector store search call
        mock_vector_store.search.assert_called_once_with('test query', k=2)
        
        # Test validation
        response = client.post(
            '/api/vector-search',
            json={'limit': 2}  # Missing query
        )
        assert response.status_code == 400
    
    def test_structure_data(self, client):
        """Test the POST /structure-data endpoint."""
        # Make request
        response = client.post(
            '/api/structure-data',
            json={
                'text': 'Sample text to structure',
                'schema': {
                    'title': {'type': 'string'},
                    'summary': {'type': 'string'}
                }
            }
        )
        
        # Verify response
        assert response.status_code == 200
        data = json.loads(response.data)
        
        # Verify structured data
        assert 'structured_data' in data
        assert 'title' in data['structured_data']
        
        # Test validation
        response = client.post(
            '/api/structure-data',
            json={'text': 'Sample text'}  # Missing schema
        )
        assert response.status_code == 400
    
    def test_yaml_validator(self, client):
        """Test the POST /yaml-validator endpoint."""
        # Valid YAML
        response = client.post(
            '/api/yaml-validator',
            json={'yaml': 'start_urls:\n  - https://example.com\nmax_depth: 2'}
        )
        
        # Verify response
        assert response.status_code == 200
        data = json.loads(response.data)
        
        # Verify validation result
        assert data['valid'] == True
        assert 'parsed_config' in data
        assert data['parsed_config']['start_urls'] == ['https://example.com']
        assert data['parsed_config']['max_depth'] == 2
        
        # Invalid YAML
        response = client.post(
            '/api/yaml-validator',
            json={'yaml': 'invalid: - yaml'}
        )
        
        # Verify response
        assert response.status_code == 400
        data = json.loads(response.data)
        assert data['valid'] == False
        assert 'error' in data
        
        # Missing YAML
        response = client.post(
            '/api/yaml-validator',
            json={}
        )
        
        assert response.status_code == 400

if __name__ == "__main__":
    pytest.main()