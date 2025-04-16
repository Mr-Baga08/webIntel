import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool

from ..models import Base

# Get database URL from environment or use default SQLite
DB_URL = os.environ.get('DATABASE_URL', 'sqlite:///webintel.db')

# Create engine with appropriate pooling
engine = create_engine(
    DB_URL,
    poolclass=QueuePool,
    pool_size=100,
    max_overflow=200,
    pool_timeout=300,
    pool_recycle=3600
)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    """Initialize the database by creating all tables."""
    Base.metadata.create_all(bind=engine)
    print(f"Database initialized at {DB_URL}")

def get_db():
    """Get a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

if __name__ == "__main__":
    init_db()