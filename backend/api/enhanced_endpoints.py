"""
API endpoints for enhanced content collection and processing.
These endpoints extend the WebIntel API to support multi-domain content operations.
"""

import logging
from flask import Blueprint, jsonify, request, g
from sqlalchemy.orm import Session
from typing import Dict, Any, List, Optional
import json

from ..db.init_db import get_db
from ..integration.enhanced_content_integration import EnhancedContentIntegration
from ..models import ScrapeRun, ScrapedPage
from ..scheduler import create_scrape_job, pause_scrape_job, resume_scrape_job, stop_scrape_job
from .limiter import limiter, SCRAPE_LIMIT, SEARCH_LIMIT

logger = logging.getLogger(__name__)

# Create blueprint
enhanced_bp = Blueprint('enhanced', __name__, url_prefix='/api/enhanced')

# Add limiter
limiter.limit("100/minute")(enhanced_bp)

# API routes

@enhanced_bp.route('/collect', methods=['POST'])
@limiter.limit(SCRAPE_LIMIT)
def collect_content():
    """Collect content based on query, sources, and optional domain expertise."""
    data = request.json
    if not data:
        return jsonify({'error': 'No data provided'}), 400
        
    # Get parameters
    query = data.get('query')
    if not query:
        return jsonify({'error': 'Query is required'}), 400
    
    domain_expertise = data.get('domain_expertise')
    sources = data.get('sources', ['web', 'pdf', 'social', 'video', 'podcast', 'dataset'])
    max_items_per_source = data.get('max_items_per_source', 5)
    
    # Validate parameters
    if max_items_per_source < 1 or max_items_per_source > 20:
        return jsonify({'error': 'max_items_per_source must be between 1 and 20'}), 400
    
    valid_sources = ['web', 'pdf', 'social', 'video', 'podcast', 'dataset']
    invalid_sources = [s for s in sources if s not in valid_sources]
    if invalid_sources:
        return jsonify({'error': f'Invalid sources: {invalid_sources}. Valid options are: {valid_sources}'}), 400
    
    valid_domains = ['general', 'marketing', 'legal', 'academic', 'technical']
    if domain_expertise and domain_expertise not in valid_domains:
        return jsonify({'error': f'Invalid domain expertise: {domain_expertise}. Valid options are: {valid_domains}'}), 400
    
    # Create integration
    db = next(get_db())
    try:
        integration = EnhancedContentIntegration(db_session=db, domain_expertise=domain_expertise)
        
        # Create scrape run
        run_id = integration.create_content_scrape_run(
            query=query,
            sources=sources,
            max_items_per_source=max_items_per_source
        )
        
        # Return run ID (actual scraping will be done in background)
        return jsonify({
            'run_id': run_id,
            'query': query,
            'domain_expertise': domain_expertise,
            'sources': sources,
            'status': 'pending'
        })
    except Exception as e:
        logger.error(f"Error creating content scrape job: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()

@enhanced_bp.route('/execute/<int:run_id>', methods=['POST'])
@limiter.limit(SCRAPE_LIMIT)
def execute_content_scrape(run_id):
    """Execute a previously created enhanced content scrape run."""
    # Create integration
    db = next(get_db())
    try:
        # Get the run to determine the domain expertise
        run = db.query(ScrapeRun).filter(ScrapeRun.id == run_id).first()
        if not run:
            return jsonify({'error': f'Run not found with ID: {run_id}'}), 404
            
        # Get domain expertise from config
        config = run.config or {}
        domain_expertise = config.get('domain_expertise')
        
        integration = EnhancedContentIntegration(db_session=db, domain_expertise=domain_expertise)
        
        # Execute the scrape
        results = integration.execute_content_scrape(run_id)
        
        return jsonify(results)
    except ValueError as e:
        return jsonify({'error': str(e)}), 404
    except Exception as e:
        logger.error(f"Error executing content scrape: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()

@enhanced_bp.route('/process-url', methods=['POST'])
@limiter.limit(SCRAPE_LIMIT)
def process_content_url():
    """Process a single URL with optional domain expertise."""
    data = request.json
    if not data or 'url' not in data:
        return jsonify({'error': 'URL is required'}), 400
        
    url = data.get('url')
    run_id = data.get('run_id')
    domain_expertise = data.get('domain_expertise')
    
    # Validate domain if provided
    valid_domains = ['general', 'marketing', 'legal', 'academic', 'technical']
    if domain_expertise and domain_expertise not in valid_domains:
        return jsonify({'error': f'Invalid domain expertise: {domain_expertise}. Valid options are: {valid_domains}'}), 400
    
    # Create integration
    db = next(get_db())
    try:
        integration = EnhancedContentIntegration(db_session=db, domain_expertise=domain_expertise)
        
        # Process URL
        page_id = integration.process_content_url(url, run_id)
        
        return jsonify({
            'page_id': page_id,
            'url': url,
            'run_id': run_id,
            'domain_expertise': domain_expertise
        })
    except Exception as e:
        logger.error(f"Error processing URL: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()

@enhanced_bp.route('/search', methods=['POST'])
@limiter.limit(SEARCH_LIMIT)
def search_content():
    """Search for content semantically with optional domain filtering."""
    data = request.json
    if not data or 'query' not in data:
        return jsonify({'error': 'Query is required'}), 400
        
    query = data.get('query')
    run_id = data.get('run_id')
    domain = data.get('domain')
    limit = data.get('limit', 10)
    
    # Validate limit
    if limit < 1 or limit > 50:
        return jsonify({'error': 'Limit must be between 1 and 50'}), 400
    
    # Validate domain if provided
    valid_domains = ['general', 'marketing', 'legal', 'academic', 'technical']
    if domain and domain not in valid_domains:
        return jsonify({'error': f'Invalid domain: {domain}. Valid options are: {valid_domains}'}), 400
    
    # Create integration
    db = next(get_db())
    try:
        integration = EnhancedContentIntegration(db_session=db)
        
        # Search
        results = integration.search_content(query, run_id, limit)
        
        # Filter by domain if specified
        if domain:
            results = [result for result in results if result.get('domain') == domain]
        
        return jsonify({
            'query': query,
            'results': results,
            'run_id': run_id,
            'domain': domain
        })
    except Exception as e:
        logger.error(f"Error searching content: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()

@enhanced_bp.route('/domains', methods=['GET'])
def get_content_domains():
    """Get available content domains."""
    domains = [
        {
            'id': 'general',
            'name': 'General',
            'description': 'General content with no specific domain specialization'
        },
        {
            'id': 'marketing',
            'name': 'Marketing',
            'description': 'Marketing, advertising, branding, and related business content'
        },
        {
            'id': 'legal',
            'name': 'Legal',
            'description': 'Legal documents, case studies, regulations, and compliance information'
        },
        {
            'id': 'academic',
            'name': 'Academic',
            'description': 'Research papers, academic journals, educational content, and studies'
        },
        {
            'id': 'technical',
            'name': 'Technical',
            'description': 'Technical documentation, programming resources, and engineering content'
        }
    ]
    
    return jsonify({'domains': domains})

@enhanced_bp.route('/sources', methods=['GET'])
def get_content_sources():
    """Get available content data sources."""
    sources = [
        {
            'id': 'web',
            'name': 'Web Pages',
            'description': 'General content from websites, blogs, and articles'
        },
        {
            'id': 'pdf',
            'name': 'PDF Documents',
            'description': 'Documents, reports, and papers in PDF format'
        },
        {
            'id': 'social',
            'name': 'Social Media',
            'description': 'Content from Twitter/X and other social platforms'
        },
        {
            'id': 'video',
            'name': 'Video Content',
            'description': 'Videos, lectures, tutorials from YouTube and other platforms'
        },
        {
            'id': 'podcast',
            'name': 'Podcasts',
            'description': 'Podcast episodes and interviews'
        },
        {
            'id': 'dataset',
            'name': 'Datasets',
            'description': 'Structured datasets from Kaggle, HuggingFace, and other sources'
        }
    ]
    
    return jsonify({'sources': sources})

@enhanced_bp.route('/run/<int:run_id>/sources', methods=['GET'])
def get_content_run_sources(run_id):
    """Get source breakdown for a content run."""
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
            # Add name based on ID
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
        logger.error(f"Error getting content run sources: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()

@enhanced_bp.route('/run/<int:run_id>/domains', methods=['GET'])
def get_content_run_domains(run_id):
    """Get domain breakdown for a content run."""
    db = next(get_db())
    try:
        # Get pages for this run
        pages = db.query(ScrapedPage).filter(ScrapedPage.scrape_run_id == run_id).all()
        
        # Count by domain
        domain_counts = {}
        for page in pages:
            domain = page.page_metadata.get('domain', 'general')
            if domain not in domain_counts:
                domain_counts[domain] = 0
            domain_counts[domain] += 1
        
        # Format response
        domains = []
        for domain_id, count in domain_counts.items():
            domain = {
                'id': domain_id,
                'count': count,
                'name': domain_id.capitalize()
            }
            domains.append(domain)
        
        return jsonify({
            'run_id': run_id,
            'domains': domains,
            'total': len(pages)
        })
    except Exception as e:
        logger.error(f"Error getting content run domains: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()

@enhanced_bp.route('/detect-domain', methods=['POST'])
def detect_content_domain():
    """Detect the domain of provided text content."""
    data = request.json
    if not data or 'text' not in data:
        return jsonify({'error': 'Text is required'}), 400
    
    text = data.get('text')
    metadata = data.get('metadata', {})
    
    try:
        from ..scraper.domain_analyzers import detect_content_domain
        
        domain = detect_content_domain(text, metadata)
        
        return jsonify({
            'domain': domain,
            'confidence': 0.85  # Placeholder - would be calculated by a real implementation
        })
    except Exception as e:
        logger.error(f"Error detecting content domain: {str(e)}")
        return jsonify({'error': str(e)}), 500