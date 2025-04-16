import pytest
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.models import Base, ScrapeRun, ScrapedPage, PageLink, VectorEmbedding

# Use in-memory SQLite for testing
@pytest.fixture
def engine():
    return create_engine('sqlite:///:memory:')

@pytest.fixture
def tables(engine):
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)

@pytest.fixture
def session(engine, tables):
    connection = engine.connect()
    transaction = connection.begin()
    Session = sessionmaker(bind=connection)
    session = Session()
    
    yield session
    
    session.close()
    transaction.rollback()
    connection.close()

class TestScrapeRunModel:
    """Tests for the ScrapeRun model."""
    
    def test_create_scrape_run(self, session):
        """Test creating a ScrapeRun."""
        run = ScrapeRun(
            query="test query",
            status="pending",
            max_depth=2
        )
        session.add(run)
        session.commit()
        
        # Verify
        assert run.id is not None
        assert run.query == "test query"
        assert run.status == "pending"
        assert run.max_depth == 2
        assert run.created_at is not None
        assert run.pages_crawled == 0
        
        # Test repr
        assert f"<ScrapeRun(id={run.id}, query='test query', status='pending')" in repr(run)
    
    def test_scrape_run_relationships(self, session):
        """Test ScrapeRun relationships."""
        # Create run
        run = ScrapeRun(
            query="test query",
            status="pending"
        )
        session.add(run)
        session.commit()
        
        # Create pages
        page1 = ScrapedPage(
            scrape_run_id=run.id,
            url="https://example.com/1",
            title="Page 1",
            crawl_depth=0
        )
        page2 = ScrapedPage(
            scrape_run_id=run.id,
            url="https://example.com/2",
            title="Page 2",
            crawl_depth=1
        )
        session.add_all([page1, page2])
        session.commit()
        
        # Verify relationship
        assert len(run.pages) == 2
        assert run.pages[0].title == "Page 1"
        assert run.pages[1].title == "Page 2"
        
        # Test cascade delete
        session.delete(run)
        session.commit()
        
        # Pages should be deleted
        assert session.query(ScrapedPage).count() == 0

class TestScrapedPageModel:
    """Tests for the ScrapedPage model."""
    
    def test_create_scraped_page(self, session):
        """Test creating a ScrapedPage."""
        # Create run first
        run = ScrapeRun(
            query="test query",
            status="completed"
        )
        session.add(run)
        session.commit()
        
        # Create page
        page = ScrapedPage(
            scrape_run_id=run.id,
            url="https://example.com",
            title="Example Page",
            crawl_depth=1,
            content_text="Example content",
            relevance_score=0.85,
            page_metadata={"author": "Test Author", "language": "en"}
        )
        session.add(page)
        session.commit()
        
        # Verify
        assert page.id is not None
        assert page.scrape_run_id == run.id
        assert page.url == "https://example.com"
        assert page.title == "Example Page"
        assert page.crawl_depth == 1
        assert page.content_text == "Example content"
        assert page.crawled_at is not None
        assert page.relevance_score == 0.85
        assert page.metadata["author"] == "Test Author"
        
        # Test repr
        assert f"<ScrapedPage(id={page.id}, url='https://example.com', title='Example Page')" in repr(page)
    
    def test_page_relationships(self, session):
        """Test ScrapedPage relationships."""
        # Create run
        run = ScrapeRun(
            query="test query",
            status="completed"
        )
        session.add(run)
        session.commit()
        
        # Create page
        page = ScrapedPage(
            scrape_run_id=run.id,
            url="https://example.com",
            title="Example Page"
        )
        session.add(page)
        session.commit()
        
        # Create links
        link1 = PageLink(
            page_id=page.id,
            url="https://example.com/link1",
            anchor_text="Link 1",
            is_internal=True
        )
        link2 = PageLink(
            page_id=page.id,
            url="https://external.com/link",
            anchor_text="External Link",
            is_internal=False
        )
        session.add_all([link1, link2])
        session.commit()
        
        # Create vector embedding
        embedding = VectorEmbedding(
            page_id=page.id,
            embedding_type="sentence-bert",
            vector_id="vec123"
        )
        session.add(embedding)
        session.commit()
        
        # Verify relationships
        assert page.scrape_run == run
        assert len(page.links) == 2
        assert page.links[0].url == "https://example.com/link1"
        assert page.links[1].url == "https://external.com/link"
        
        # Test cascade delete
        session.delete(page)
        session.commit()
        
        # Links should be deleted, but run should remain
        assert session.query(PageLink).count() == 0
        assert session.query(VectorEmbedding).count() == 0
        assert session.query(ScrapeRun).count() == 1

class TestPageLinkModel:
    """Tests for the PageLink model."""
    
    def test_create_page_link(self, session):
        """Test creating a PageLink."""
        # Create run and page first
        run = ScrapeRun(query="test", status="completed")
        session.add(run)
        session.commit()
        
        page = ScrapedPage(
            scrape_run_id=run.id,
            url="https://example.com",
            title="Example"
        )
        session.add(page)
        session.commit()
        
        # Create link
        link = PageLink(
            page_id=page.id,
            url="https://example.com/link",
            anchor_text="Link Text",
            is_internal=True,
            is_crawled=False
        )
        session.add(link)
        session.commit()
        
        # Verify
        assert link.id is not None
        assert link.page_id == page.id
        assert link.url == "https://example.com/link"
        assert link.anchor_text == "Link Text"
        assert link.is_internal == True
        assert link.is_crawled == False
        
        # Test repr
        assert f"<PageLink(id={link.id}, url='https://example.com/link'" in repr(link)
        
        # Test relationship
        assert link.page == page

class TestVectorEmbeddingModel:
    """Tests for the VectorEmbedding model."""
    
    def test_create_vector_embedding(self, session):
        """Test creating a VectorEmbedding."""
        # Create run and page first
        run = ScrapeRun(query="test", status="completed")
        session.add(run)
        session.commit()
        
        page = ScrapedPage(
            scrape_run_id=run.id,
            url="https://example.com",
            title="Example"
        )
        session.add(page)
        session.commit()
        
        # Create embedding
        embedding = VectorEmbedding(
            page_id=page.id,
            embedding_type="sentence-bert",
            vector_id="vec456"
        )
        session.add(embedding)
        session.commit()
        
        # Verify
        assert embedding.id is not None
        assert embedding.page_id == page.id
        assert embedding.embedding_type == "sentence-bert"
        assert embedding.vector_id == "vec456"
        
        # Test repr
        assert f"<VectorEmbedding(id={embedding.id}, page_id={page.id}, vector_id='vec456')" in repr(embedding)

if __name__ == "__main__":
    pytest.main()