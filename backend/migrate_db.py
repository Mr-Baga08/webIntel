"""
Script to migrate the database structure.
Run this with:
python migrate_db.py
"""

import os
import sys
import logging
import sqlite3

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def migrate_database():
    """Migrate the database structure to match new models."""
    
    # Connect to SQLite database
    db_path = os.environ.get('DATABASE_PATH', 'backend/webintel.db')
    
    if not os.path.exists(db_path):
        logger.error(f"Database file not found: {db_path}")
        return
    
    logger.info(f"Migrating database: {db_path}")
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Check if we need to rename metadata column
        cursor.execute("PRAGMA table_info(scraped_pages)")
        columns = cursor.fetchall()
        column_names = [col[1] for col in columns]
        
        if 'metadata' in column_names and 'page_metadata' not in column_names:
            logger.info("Renaming 'metadata' column to 'page_metadata'")
            
            # SQLite doesn't support directly renaming columns, so we need to:
            # 1. Create a new table with the desired structure
            # 2. Copy data from the old table
            # 3. Drop the old table
            # 4. Rename the new table
            
            # 1. Create temporary table with new structure
            cursor.execute("""
            CREATE TABLE scraped_pages_new (
                id INTEGER PRIMARY KEY,
                scrape_run_id INTEGER NOT NULL,
                url TEXT NOT NULL,
                title TEXT,
                crawl_depth INTEGER,
                content_text TEXT,
                content_html TEXT,
                crawled_at TIMESTAMP,
                page_metadata JSON,
                embedding_id TEXT,
                relevance_score REAL,
                structured_data JSON,
                FOREIGN KEY (scrape_run_id) REFERENCES scrape_runs (id)
            )
            """)
            
            # 2. Copy data from old table to new table
            cursor.execute("""
            INSERT INTO scraped_pages_new 
            SELECT 
                id, 
                scrape_run_id, 
                url, 
                title, 
                crawl_depth, 
                content_text, 
                content_html, 
                crawled_at, 
                metadata, 
                embedding_id, 
                relevance_score, 
                structured_data 
            FROM scraped_pages
            """)
            
            # 3. Drop old table
            cursor.execute("DROP TABLE scraped_pages")
            
            # 4. Rename new table
            cursor.execute("ALTER TABLE scraped_pages_new RENAME TO scraped_pages")
            
            logger.info("Column renamed successfully")
            
        else:
            if 'page_metadata' in column_names:
                logger.info("Database already has 'page_metadata' column")
            else:
                logger.info("Could not find 'metadata' column to rename")
        
        # Commit the changes
        conn.commit()
        logger.info("Database migration completed successfully")
        
    except Exception as e:
        logger.error(f"Error migrating database: {str(e)}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    migrate_database()