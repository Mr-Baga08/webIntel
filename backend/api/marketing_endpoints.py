"""
API endpoints for marketing data collection and processing.
These endpoints extend the WebIntel API to support marketing-specific operations.
"""

import logging
from flask import Blueprint, jsonify, request, g
from sqlalchemy.orm import Session
from typing import Dict, Any, List, Optional
import json

from ..db.init_db import get_db
from ..integration.marketing_integration import MarketingIntegration
from ..models import ScrapeRun, ScrapedPage
from ..scheduler import create_scrape_job, pause_scrape_job, resume_scrape_job, stop_scrape_job
from .limiter import limiter, SCRAPE_LIMIT, SEARCH_LIMIT

logger = logging.getLogger(__name__)

# Create blueprint
marketing_bp = Blueprint('marketing', __name__, url_prefix='/api/marketing')

# Add limiter
limiter.limit("100/minute")(marketing_bp)

# API routes

@marketing_bp.route('/dataset/<path:dataset_ref>', methods=['GET'])
def get_marketing_dataset_info(dataset_ref):
    """Get information about a marketing dataset."""
    # Create integration
    db = next(get_db())
    try:
        from ..scraper.dataset_collector import DatasetCollector
        
        collector = DatasetCollector()
        
        # Determine source
        source = request.args.get('source', 'kaggle')
        if source == 'kaggle':
            # Search for the dataset
            datasets = collector.search_kaggle_datasets(dataset_ref, max_results=1)
            if not datasets:
                return jsonify({'error': 'Dataset not found'}), 404
                
            return jsonify({
                'dataset': datasets[0],
                'source': source
            })
        else:
            return jsonify({'error': f'Unsupported dataset source: {source}'}), 400
    except Exception as e:
        logger.error(f"Error getting dataset info: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()

@marketing_bp.route('/dataset/<path:dataset_ref>/download', methods=['POST'])
@limiter.limit(SCRAPE_LIMIT)
def download_marketing_dataset(dataset_ref):
    """Download and process a marketing dataset."""
    # Create integration
    db = next(get_db())
    try:
        # Get parameters
        data = request.json or {}
        source = data.get('source', 'kaggle')
        run_id = data.get('run_id')
        
        # Create integration
        integration = MarketingIntegration(db_session=db)
        
        # First get dataset info
        from ..scraper.dataset_collector import DatasetCollector
        collector = DatasetCollector()
        
        if source == 'kaggle':
            # Get dataset info
            datasets = collector.search_kaggle_datasets(dataset_ref, max_results=1)
            if not datasets:
                return jsonify({'error': 'Dataset not found'}), 404
                
            dataset_info = datasets[0]
            dataset_info['source'] = source
            
            # Process the dataset
            if not run_id:
                # Create a new run
                run = ScrapeRun(
                    query=f"Marketing Dataset: {dataset_info.get('title', dataset_ref)}",
                    status="running",
                    max_depth=0,
                    config={
                        "dataset_ref": dataset_ref,
                        "dataset_source": source
                    }
                )
                db.add(run)
                db.commit()
                run_id = run.id
            
            # Download and process
            result = integration._save_marketing_item(db, run_id, 'dataset', dataset_info)
            
            # Update run status
            run = db.query(ScrapeRun).filter(ScrapeRun.id == run_id).first()
            if run:
                run.status = "completed"
                run.completed_at = datetime.utcnow()
                run.pages_crawled = 1
                db.commit()
            
            return jsonify({
                'dataset': dataset_info,
                'run_id': run_id,
                'page_id': result
            })
        else:
            return jsonify({'error': f'Unsupported dataset source: {source}'}), 400
    except Exception as e:
        logger.error(f"Error downloading dataset: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()
marketing_bp.route('/execute/<int:run_id>', methods=['POST'])
@limiter.limit(SCRAPE_LIMIT)
def execute_marketing_scrape(run_id):
    """Execute a previously created marketing scrape run."""
    # Create integration
    db = next(get_db())
    try:
        integration = MarketingIntegration(db_session=db)
        
        # Execute the scrape
        results = integration.execute_marketing_scrape(run_id)
        
        return jsonify(results)
    except ValueError as e:
        return jsonify({'error': str(e)}), 404
    except Exception as e:
        logger.error(f"Error executing marketing scrape: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()

@marketing_bp.route('/process-url', methods=['POST'])
@limiter.limit(SCRAPE_LIMIT)
def process_marketing_url():
    """Process a single marketing URL."""
    data = request.json
    if not data or 'url' not in data:
        return jsonify({'error': 'URL is required'}), 400
        
    url = data.get('url')
    run_id = data.get('run_id')
    
    # Create integration
    db = next(get_db())
    try:
        integration = MarketingIntegration(db_session=db)
        
        # Process URL
        page_id = integration.process_marketing_url(url, run_id)
        
        return jsonify({
            'page_id': page_id,
            'url': url,
            'run_id': run_id
        })
    except Exception as e:
        logger.error(f"Error processing marketing URL: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()

@marketing_bp.route('/search', methods=['POST'])
@limiter.limit(SEARCH_LIMIT)
def search_marketing_content():
    """Search for marketing content semantically."""
    data = request.json
    if not data or 'query' not in data:
        return jsonify({'error': 'Query is required'}), 400
        
    query = data.get('query')
    run_id = data.get('run_id')
    limit = data.get('limit', 10)
    
    # Validate limit
    if limit < 1 or limit > 50:
        return jsonify({'error': 'Limit must be between 1 and 50'}), 400
    
    # Create integration
    db = next(get_db())
    try:
        integration = MarketingIntegration(db_session=db)
        
        # Search
        results = integration.search_marketing_content(query, run_id, limit)
        
        return jsonify({
            'query': query,
            'results': results,
            'run_id': run_id
        })
    except Exception as e:
        logger.error(f"Error searching marketing content: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()

@marketing_bp.route('/sources', methods=['GET'])
def get_marketing_sources():
    """Get available marketing data sources."""
    sources = [
        {
            'id': 'web',
            'name': 'Web Pages',
            'description': 'Marketing content from websites, blogs, and case studies'
        },
        {
            'id': 'pdf',
            'name': 'PDF Documents',
            'description': 'Marketing whitepapers, reports, and case studies in PDF format'
        },
        {
            'id': 'social',
            'name': 'Social Media',
            'description': 'Marketing content from Twitter/X and other social platforms'
        },
        {
            'id': 'video',
            'name': 'Video Content',
            'description': 'Marketing lectures, tutorials, and webinars from YouTube and other platforms'
        },
        {
            'id': 'podcast',
            'name': 'Podcasts',
            'description': 'Marketing podcast episodes and interviews'
        },
        {
            'id': 'dataset',
            'name': 'Datasets',
            'description': 'Marketing-related datasets from Kaggle, HuggingFace, and other sources'
        }
    ]
    
    return jsonify({'sources': sources})

@marketing_bp.route('/run/<int:run_id>/sources', methods=['GET'])
def get_marketing_run_sources(run_id):
    """Get source breakdown for a marketing run."""
    db = next(get_db())
    try:
        # Get pages for this run
        pages = db.query(ScrapedPage).filter(ScrapedPage.scrape_run_id == run_id).all()
        
        # Count by source type
        source_counts = {}
        for page in pages:
            source_type = page.page_metadata.get('source_type', 'unknown')
            if source_type not in source_counts:
                source_counts[source_type] = 0
            source_counts[source_type] += 1
        
        # Format response
        sources = []
        for source_id, count in source_counts.items():
            source = {
                'id': source_id,
                'count': count
            }
            # Add name and description based on ID
            if source_id == 'web':
                source['name'] = 'Web Pages'
            elif source_id == 'pdf':
                source['name'] = 'PDF Documents'
            elif source_id == 'social':
                source['name'] = 'Social Media'
            elif source_id == 'video':
                source['name'] = 'Video Content'
            elif source_id == 'podcast':
                source['name'] = 'Podcasts'
            elif source_id == 'dataset':
                source['name'] = 'Datasets'
            else:
                source['name'] = source_id.capitalize()
                
            sources.append(source)
        
        return jsonify({
            'run_id': run_id,
            'sources': sources,
            'total': len(pages)
        })
    except Exception as e:
        logger.error(f"Error getting marketing run sources: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()

@marketing_bp.route('/collect', methods=['POST'])
@limiter.limit(SCRAPE_LIMIT)
def collect_marketing_data():
    """Collect marketing data based on query and sources."""
    data = request.json
    if not data:
        return jsonify({'error': 'No data provided'}), 400
        
    # Get parameters
    query = data.get('query')
    if not query:
        return jsonify({'error': 'Query is required'}), 400
    
    sources = data.get('sources', ['web', 'pdf', 'social', 'video', 'podcast', 'dataset'])
    max_items_per_source = data.get('max_items_per_source', 5)
    
    # Validate parameters
    if max_items_per_source < 1 or max_items_per_source > 20:
        return jsonify({'error': 'max_items_per_source must be between 1 and 20'}), 400
    
    valid_sources = ['web', 'pdf', 'social', 'video', 'podcast', 'dataset']
    invalid_sources = [s for s in sources if s not in valid_sources]
    if invalid_sources:
        return jsonify({'error': f'Invalid sources: {invalid_sources}. Valid options are: {valid_sources}'}), 400
    
    # Create integration
    db = next(get_db())
    try:
        integration = MarketingIntegration(db_session=db)
        
        # Create scrape run
        run_id = integration.create_marketing_scrape_run(
            query=query,
            sources=sources,
            max_items_per_source=max_items_per_source
        )
        
        # Return run ID (actual scraping will be done in background)
        return jsonify({
            'run_id': run_id,
            'query': query,
            'sources': sources,
            'status': 'pending'
        })
    except Exception as e:
        logger.error(f"Error creating marketing scrape job: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()