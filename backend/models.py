from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Float, JSON, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()

class ScrapeRun(Base):
    """Main container for a scraping job."""
    __tablename__ = "scrape_runs"
    
    id = Column(Integer, primary_key=True)
    query = Column(String(255), nullable=False)
    status = Column(String(50), default="pending")  # pending, running, paused, completed, failed
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    max_depth = Column(Integer, default=2)
    pages_crawled = Column(Integer, default=0)
    pages_total = Column(Integer, default=0)
    config = Column(JSON, nullable=True)  # For Crawl4AI-style YAML config
    
    # Relationship to scraped pages
    pages = relationship("ScrapedPage", back_populates="scrape_run", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<ScrapeRun(id={self.id}, query='{self.query}', status='{self.status}')>"


class ScrapedPage(Base):
    """Individual web page that has been scraped."""
    __tablename__ = "scraped_pages"
    
    id = Column(Integer, primary_key=True)
    scrape_run_id = Column(Integer, ForeignKey("scrape_runs.id"), nullable=False)
    url = Column(String(2048), nullable=False)
    title = Column(String(512), nullable=True)
    crawl_depth = Column(Integer, default=0)
    content_text = Column(Text, nullable=True)
    content_html = Column(Text, nullable=True)
    crawled_at = Column(DateTime, default=datetime.utcnow)
    page_metadata = Column(JSON, nullable=True)  # Renamed from 'metadata' to avoid conflict
    embedding_id = Column(String(255), nullable=True)  # Reference to vector store
    relevance_score = Column(Float, nullable=True)  # NLP-calculated relevance to query
    structured_data = Column(JSON, nullable=True)  # For LLM-parsed structured output
    
    # Relationship back to parent scrape run
    scrape_run = relationship("ScrapeRun", back_populates="pages")
    
    # Relationships to child entities
    links = relationship("PageLink", back_populates="page", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<ScrapedPage(id={self.id}, url='{self.url}', title='{self.title}')>"


class PageLink(Base):
    """Links found on a page."""
    __tablename__ = "page_links"
    
    id = Column(Integer, primary_key=True)
    page_id = Column(Integer, ForeignKey("scraped_pages.id"), nullable=False)
    url = Column(String(2048), nullable=False)
    anchor_text = Column(String(512), nullable=True)
    is_internal = Column(Boolean, default=False)
    is_crawled = Column(Boolean, default=False)
    
    # Relationship back to parent page
    page = relationship("ScrapedPage", back_populates="links")
    
    def __repr__(self):
        return f"<PageLink(id={self.id}, url='{self.url}', is_internal={self.is_internal})>"


class VectorEmbedding(Base):
    """Stores vector embeddings for semantic search."""
    __tablename__ = "vector_embeddings"
    
    id = Column(Integer, primary_key=True)
    page_id = Column(Integer, ForeignKey("scraped_pages.id"), nullable=False)
    embedding_type = Column(String(50), default="sentence-bert")  # Type of embedding model used
    vector_id = Column(String(255), nullable=False)  # ID in FAISS or other vector store
    
    def __repr__(self):
        return f"<VectorEmbedding(id={self.id}, page_id={self.page_id}, vector_id='{self.vector_id}')>"