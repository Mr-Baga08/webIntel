import pytest
from unittest.mock import patch, MagicMock, Mock
import yaml
from bs4 import BeautifulSoup

from backend.scraper.base_scraper import BaseScraper, get_page_content
from backend.scraper.crawler import Crawler, crawl_with_config, CrawlConfig
from backend.scraper.metadata import extract_metadata, extract_structured_data
from backend.scraper.controller import ScraperControl, scrape_control


class TestBaseScraper:
    """Tests for the BaseScraper class."""
    
    @patch('backend.scraper.base_scraper.sync_playwright')
    def test_get_page_content(self, mock_playwright):
        """Test the get_page_content method."""
        # Mock Playwright objects
        mock_browser = MagicMock()
        mock_context = MagicMock()
        mock_page = MagicMock()
        
        # Set up the mock chain
        mock_playwright.return_value.__enter__.return_value.chromium.launch.return_value = mock_browser
        mock_browser.new_context.return_value = mock_context
        mock_context.new_page.return_value = mock_page
        
        # Mock content and title
        mock_page.content.return_value = "<html><body>Test content</body></html>"
        mock_page.title.return_value = "Test Page"
        mock_page.url = "https://example.com/test"
        
        # Create scraper and call method
        scraper = BaseScraper()
        html, metadata = scraper.get_page_content("https://example.com/test")
        
        # Assertions
        assert html == "<html><body>Test content</body></html>"
        assert metadata["title"] == "Test Page"
        assert metadata["url"] == "https://example.com/test"
        
        # Verify calls
        mock_playwright.return_value.__enter__.return_value.chromium.launch.assert_called_once()
        mock_browser.new_context.assert_called_once()
        mock_context.new_page.assert_called_once()
        mock_page.goto.assert_called_once_with("https://example.com/test", timeout=600000000)
        mock_page.wait_for_load_state.assert_called_once()
        mock_page.content.assert_called_once()
        mock_page.close.assert_called_once()
        mock_context.close.assert_called_once()
        mock_browser.close.assert_called_once()
    
    def test_normalize_url(self):
        """Test the normalize_url method."""
        scraper = BaseScraper()
        
        # Test absolute URL
        assert scraper.normalize_url("https://example.com/page") == "https://example.com/page"
        
        # Test relative URL with base URL
        assert scraper.normalize_url("/page", "https://example.com") == "https://example.com/page"
        
        # Test URL with fragment (should be removed)
        assert scraper.normalize_url("https://example.com/page#section") == "https://example.com/page"
        
        # Test URL without scheme (should default to https)
        assert scraper.normalize_url("example.com/page") == "https://example.com/page"
        
        # Test None URL
        assert scraper.normalize_url(None) is None


class TestCrawler:
    """Tests for the Crawler class."""
    
    def test_crawler_init(self):
        """Test Crawler initialization."""
        # Test with default config
        crawler = Crawler("test_job")
        assert crawler.job_id == "test_job"
        assert crawler.config.max_depth == 2
        assert crawler.config.start_urls == []
        
        # Test with custom config
        config = CrawlConfig(
            start_urls=["https://example.com"],
            max_depth=3,
            max_pages=50
        )
        crawler = Crawler("test_job", config=config)
        assert crawler.job_id == "test_job"
        assert crawler.config.max_depth == 3
        assert crawler.config.start_urls == ["https://example.com"]
        assert crawler.config.max_pages == 50
    
    def test_is_allowed_domain(self):
        """Test the is_allowed_domain method."""
        # Test with no allowed domains (should allow all)
        crawler = Crawler("test_job")
        assert crawler.is_allowed_domain("https://example.com")
        assert crawler.is_allowed_domain("https://another-domain.com")
        
        # Test with allowed domains
        config = CrawlConfig(
            start_urls=["https://example.com"],
            allowed_domains=["example.com", "subdomain.example.com"]
        )
        crawler = Crawler("test_job", config=config)
        assert crawler.is_allowed_domain("https://example.com")
        assert crawler.is_allowed_domain("https://subdomain.example.com")
        assert not crawler.is_allowed_domain("https://another-domain.com")
    
    @patch('backend.scraper.crawler.BeautifulSoup')
    def test_extract_links(self, mock_bs):
        """Test the extract_links method."""
        # Mock BeautifulSoup
        mock_soup = MagicMock()
        mock_bs.return_value = mock_soup
        
        # Mock link elements
        mock_links = [
            # Internal link
            MagicMock(attrs={'href': '/page1'}, text="Page 1"),
            # External link
            MagicMock(attrs={'href': 'https://external.com/page'}, text="External"),
            # Javascript link (should be skipped)
            MagicMock(attrs={'href': 'javascript:void(0)'}, text="JS Link"),
            # Empty href (should be skipped)
            MagicMock(attrs={'href': ''}, text="Empty Link"),
            # Another domain but not external (should include when follow_external_links=True)
            MagicMock(attrs={'href': 'https://example.org'}, text="Another Domain")
        ]
        mock_soup.find_all.return_value = mock_links
        
        # Create crawler and extract links
        config = CrawlConfig(
            start_urls=["https://example.com"],
            allowed_domains=["example.com"],
            follow_external_links=True
        )
        crawler = Crawler("test_job", config=config)
        links = crawler.extract_links("<html></html>", "https://example.com")
        
        # Should have 3 valid links (internal, external, and another domain)
        assert len(links) == 3
        
        # Internal link
        assert links[0]['url'] == "https://example.com/page1"
        assert links[0]['anchor_text'] == "Page 1"
        assert links[0]['is_internal'] == True
        
        # External link
        assert links[1]['url'] == "https://external.com/page"
        assert links[1]['anchor_text'] == "External"
        assert links[1]['is_internal'] == False
        
        # Another domain
        assert links[2]['url'] == "https://example.org"
        assert links[2]['anchor_text'] == "Another Domain"
        assert links[2]['is_internal'] == False
        
        # Test with follow_external_links=False
        config.follow_external_links = False
        crawler = Crawler("test_job", config=config)
        links = crawler.extract_links("<html></html>", "https://example.com")
        
        # Should have only internal link
        assert len(links) == 1
        assert links[0]['url'] == "https://example.com/page1"
    
    @patch('backend.scraper.crawler.Crawler.extract_links')
    @patch('backend.scraper.crawler.Crawler.crawl_url')
    def test_crawl(self, mock_crawl_url, mock_extract_links):
        """Test the crawl method."""
        # Mock the crawl_url method
        mock_crawl_url.side_effect = [
            # First page
            {
                'url': 'https://example.com',
                'depth': 0,
                'html': '<html></html>',
                'title': 'Example',
                'text': 'Example content',
                'metadata': {},
                'links': [{'url': 'https://example.com/page1', 'anchor_text': 'Page 1', 'is_internal': True}]
            },
            # Second page
            {
                'url': 'https://example.com/page1',
                'depth': 1,
                'html': '<html></html>',
                'title': 'Page 1',
                'text': 'Page 1 content',
                'metadata': {},
                'links': []
            }
        ]
        
        # Create config and crawler
        config = CrawlConfig(
            start_urls=["https://example.com"],
            max_depth=2,
            max_pages=10
        )
        crawler = Crawler("test_job", config=config)
        
        # Mock scrape_control
        with patch('backend.scraper.crawler.scrape_control') as mock_control:
            mock_control.should_continue.return_value = True
            mock_control.is_paused.return_value = False
            
            # Call crawl method
            results = crawler.crawl()
            
            # Verify results
            assert len(results) == 2
            assert results[0]['url'] == 'https://example.com'
            assert results[1]['url'] == 'https://example.com/page1'
            
            # Verify calls
            assert mock_crawl_url.call_count == 2
            mock_control.start.assert_called_once_with("test_job")
            mock_control.complete.assert_called_once_with("test_job")
    
    def test_from_yaml_config(self):
        """Test creating a crawler from YAML configuration."""
        yaml_str = """
        start_urls:
          - https://example.com
        max_depth: 3
        max_pages: 50
        follow_external_links: true
        wait_time: 0.5
        css_selectors:
          content: article
          title: h1
        """
        
        crawler = Crawler.from_yaml_config("test_job", yaml_str)
        
        assert crawler.job_id == "test_job"
        assert crawler.config.start_urls == ["https://example.com"]
        assert crawler.config.max_depth == 3
        assert crawler.config.max_pages == 50
        assert crawler.config.follow_external_links == True
        assert crawler.config.wait_time == 0.5
        assert crawler.config.css_selectors == {"content": "article", "title": "h1"}


class TestMetadata:
    """Tests for the metadata extraction functions."""
    
    @patch('backend.scraper.metadata.Article')
    def test_extract_metadata_newspaper(self, mock_article_class):
        """Test metadata extraction with newspaper3k."""
        # Mock Article instance
        mock_article = MagicMock()
        mock_article_class.return_value = mock_article
        
        # Set mock article properties
        mock_article.title = "Test Title"
        mock_article.authors = ["Author 1", "Author 2"]
        mock_article.publish_date = "2023-01-01"
        mock_article.text = "Test content"
        mock_article.top_image = "https://example.com/image.jpg"
        mock_article.keywords = ["test", "example"]
        mock_article.summary = "Test summary"
        
        # Call extract_metadata
        metadata = extract_metadata("https://example.com", "<html></html>")
        
        # Verify results
        assert metadata["title"] == "Test Title"
        assert metadata["authors"] == ["Author 1", "Author 2"]
        assert metadata["published_date"] == "2023-01-01"
        assert metadata["text"] == "Test content"
        assert metadata["top_image"] == "https://example.com/image.jpg"
        assert metadata["keywords"] == ["test", "example"]
        assert metadata["summary"] == "Test summary"
        
        # Verify newspaper calls
        mock_article_class.assert_called_once_with("https://example.com", config=mock_article.config)
        mock_article.set_html.assert_called_once_with("<html></html>")
        mock_article.parse.assert_called_once()
        mock_article.nlp.assert_called_once()
    
    @patch('backend.scraper.metadata.extract_structured_data')
    @patch('backend.scraper.metadata.BeautifulSoup')
    def test_extract_structured_data(self, mock_bs, mock_extract):
        """Test structured data extraction."""
        # Mock BeautifulSoup
        mock_soup = MagicMock()
        mock_bs.return_value = mock_soup
        
        # Mock script tags with JSON-LD
        mock_scripts = [
            MagicMock(string='{"@type": "Article", "headline": "Test"}'),
            MagicMock(string='{"@type": "Person", "name": "John Doe"}')
        ]
        mock_soup.find_all.return_value = mock_scripts
        
        # Call extract_structured_data
        structured_data = extract_structured_data("<html></html>")
        
        # Verify results
        assert len(structured_data) == 2
        assert structured_data[0]["@type"] == "Article"
        assert structured_data[0]["headline"] == "Test"
        assert structured_data[1]["@type"] == "Person"
        assert structured_data[1]["name"] == "John Doe"


class TestScraperControl:
    """Tests for the ScraperControl class."""
    
    def test_controller_lifecycle(self):
        """Test the controller lifecycle methods."""
        # Create controller
        controller = ScraperControl()
        
        # Register job
        job_id = controller.register_job("test_job")
        assert job_id == "test_job"
        assert "test_job" in controller.jobs
        assert controller.jobs["test_job"]["running"] == False
        
        # Start job
        controller.start("test_job")
        assert controller.jobs["test_job"]["running"] == True
        assert controller.jobs["test_job"]["paused"] == False
        assert controller.jobs["test_job"]["stats"]["start_time"] is not None
        
        # Check status
        assert controller.get_status("test_job") == "running"
        assert controller.should_continue("test_job") == True
        assert controller.is_paused("test_job") == False
        
        # Pause job
        success = controller.pause("test_job")
        assert success == True
        assert controller.jobs["test_job"]["paused"] == True
        assert controller.get_status("test_job") == "paused"
        
        # Resume job
        success = controller.resume("test_job")
        assert success == True
        assert controller.jobs["test_job"]["paused"] == False
        assert controller.get_status("test_job") == "running"
        
        # Update stats
        controller.update_stats("test_job", pages_crawled=10, bytes_downloaded=1024)
        assert controller.jobs["test_job"]["stats"]["pages_crawled"] == 10
        assert controller.jobs["test_job"]["stats"]["bytes_downloaded"] == 1024
        
        # Complete job
        success = controller.complete("test_job")
        assert success == True
        assert controller.jobs["test_job"]["running"] == False
        assert controller.jobs["test_job"]["stats"]["end_time"] is not None
        assert controller.get_status("test_job") == "completed"
        
        # Cleanup job
        success = controller.cleanup_job("test_job")
        assert success == True
        assert "test_job" not in controller.jobs
        assert controller.get_status("test_job") is None
    
    def test_nonexistent_job(self):
        """Test controller methods with nonexistent job ID."""
        controller = ScraperControl()
        
        # These should not raise errors but return appropriate values
        assert controller.get_status("nonexistent") is None
        assert controller.should_continue("nonexistent") == False
        assert controller.is_paused("nonexistent") == False
        assert controller.get_stats("nonexistent") is None
        
        # These should return False for nonexistent jobs
        assert controller.pause("nonexistent") == False
        assert controller.resume("nonexistent") == False
        assert controller.stop("nonexistent") == False
        assert controller.complete("nonexistent") == False
        assert controller.update_stats("nonexistent", pages_crawled=10) == False
        assert controller.cleanup_job("nonexistent") == False


if __name__ == "__main__":
    pytest.main()