import logging
from flask import Blueprint, jsonify, request, g
from sqlalchemy.orm import Session
from typing import Dict, Any, List, Optional
import yaml
import json

from ..db.init_db import get_db
from ..models import ScrapeRun, ScrapedPage, PageLink
from ..scheduler import (
    create_scrape_job, 
    create_crawl_job_from_yaml,
    pause_scrape_job, 
    resume_scrape_job, 
    stop_scrape_job
)
from ..search.bing import search_bing
from ..search.vector_store import get_vector_store
from ..search.ranker import rank_search_results
from .limiter import limiter, SCRAPE_LIMIT, SEARCH_LIMIT, CONTROL_LIMIT

logger = logging.getLogger(__name__)

# Create blueprint
api_bp = Blueprint('api', __name__, url_prefix='/api')

# Add limiter
limiter.limit("100/minute")(api_bp)

# API routes

@api_bp.route('/runs', methods=['GET'])
def get_runs():
    """Get all scrape runs."""
    db = next(get_db())
    try:
        # Get query parameters
        limit = request.args.get('limit', default=10, type=int)
        offset = request.args.get('offset', default=0, type=int)
        
        # Get runs from database
        runs = (
            db.query(ScrapeRun)
            .order_by(ScrapeRun.created_at.desc())
            .limit(limit)
            .offset(offset)
            .all()
        )
        
        # Format response
        result = []
        for run in runs:
            result.append({
                'id': run.id,
                'query': run.query,
                'status': run.status,
                'created_at': run.created_at.isoformat() if run.created_at else None,
                'completed_at': run.completed_at.isoformat() if run.completed_at else None,
                'pages_crawled': run.pages_crawled,
                'pages_total': run.pages_total
            })
            
        return jsonify({
            'runs': result,
            'total': db.query(ScrapeRun).count(),
            'limit': limit,
            'offset': offset
        })
        
    finally:
        db.close()

@api_bp.route('/runs/<int:run_id>', methods=['GET'])
def get_run(run_id):
    """Get a specific scrape run."""
    db = next(get_db())
    try:
        # Get run from database
        run = db.query(ScrapeRun).filter(ScrapeRun.id == run_id).first()
        
        if not run:
            return jsonify({'error': 'Run not found'}), 404
            
        # Get pages count
        pages_count = db.query(ScrapedPage).filter(ScrapedPage.scrape_run_id == run_id).count()
        
        # Format response
        result = {
            'id': run.id,
            'query': run.query,
            'status': run.status,
            'created_at': run.created_at.isoformat() if run.created_at else None,
            'updated_at': run.updated_at.isoformat() if run.updated_at else None,
            'completed_at': run.completed_at.isoformat() if run.completed_at else None,
            'max_depth': run.max_depth,
            'pages_crawled': run.pages_crawled,
            'pages_total': pages_count,
            'config': run.config
        }
        
        return jsonify(result)
        
    finally:
        db.close()

@api_bp.route('/runs/<int:run_id>/pages', methods=['GET'])
def get_run_pages(run_id):
    """Get pages for a specific scrape run."""
    db = next(get_db())
    try:
        # Get query parameters
        limit = request.args.get('limit', default=20, type=int)
        offset = request.args.get('offset', default=0, type=int)
        order_by = request.args.get('order_by', default='crawled_at', type=str)
        order_dir = request.args.get('order_dir', default='desc', type=str)
        
        # Validate order_by
        valid_order_by = ['crawled_at', 'url', 'title', 'crawl_depth', 'relevance_score']
        if order_by not in valid_order_by:
            order_by = 'crawled_at'
            
        # Build order clause
        if order_by == 'relevance_score':
            # Handle NULL values for relevance_score
            if order_dir.lower() == 'asc':
                order_clause = ScrapedPage.relevance_score.asc().nullslast()
            else:
                order_clause = ScrapedPage.relevance_score.desc().nullsfirst()
        else:
            # Standard ordering
            order_attr = getattr(ScrapedPage, order_by)
            order_clause = order_attr.asc() if order_dir.lower() == 'asc' else order_attr.desc()
        
        # Check if run exists
        run = db.query(ScrapeRun).filter(ScrapeRun.id == run_id).first()
        if not run:
            return jsonify({'error': 'Run not found'}), 404
            
        # Get pages from database
        pages = (
            db.query(ScrapedPage)
            .filter(ScrapedPage.scrape_run_id == run_id)
            .order_by(order_clause)
            .limit(limit)
            .offset(offset)
            .all()
        )
        
        # Format response
        result = []
        for page in pages:
            page_data = {
                'id': page.id,
                'url': page.url,
                'title': page.title,
                'crawl_depth': page.crawl_depth,
                'crawled_at': page.crawled_at.isoformat() if page.crawled_at else None,
                'relevance_score': page.relevance_score,
                'embedding_id': page.embedding_id,
                'has_content': bool(page.content_text),
                'has_structured_data': bool(page.structured_data)
            }
            
            # Add snippet if requested
            if request.args.get('include_snippet', 'true').lower() == 'true':
                content = page.content_text or ''
                page_data['snippet'] = content[:300] + '...' if len(content) > 300 else content
                
            result.append(page_data)
            
        return jsonify({
            'pages': result,
            'total': db.query(ScrapedPage).filter(ScrapedPage.scrape_run_id == run_id).count(),
            'limit': limit,
            'offset': offset
        })
        
    finally:
        db.close()

@api_bp.route('/pages/<int:page_id>', methods=['GET'])
def get_page(page_id):
    """Get a specific page."""
    db = next(get_db())
    try:
        # Get page from database
        page = db.query(ScrapedPage).filter(ScrapedPage.id == page_id).first()
        
        if not page:
            return jsonify({'error': 'Page not found'}), 404
            
        # Format response
        result = {
            'id': page.id,
            'scrape_run_id': page.scrape_run_id,
            'url': page.url,
            'title': page.title,
            'crawl_depth': page.crawl_depth,
            'content_text': page.content_text,
            'crawled_at': page.crawled_at.isoformat() if page.crawled_at else None,
            'page_metadata': page.page_metadata,
            'relevance_score': page.relevance_score,
            'embedding_id': page.embedding_id,
            'structured_data': page.structured_data
        }
        
        # Add HTML content if requested
        if request.args.get('include_html', 'false').lower() == 'true':
            result['content_html'] = page.content_html
            
        # Get links if requested
        if request.args.get('include_links', 'false').lower() == 'true':
            links = db.query(PageLink).filter(PageLink.page_id == page_id).all()
            result['links'] = [{
                'url': link.url,
                'anchor_text': link.anchor_text,
                'is_internal': link.is_internal,
                'is_crawled': link.is_crawled
            } for link in links]
            
        return jsonify(result)
        
    finally:
        db.close()

@api_bp.route('/runs', methods=['POST'])
@limiter.limit(SCRAPE_LIMIT)
def create_run():
    """Create a new scrape run."""
    data = request.json
    if not data:
        return jsonify({'error': 'No data provided'}), 400
        
    # Check if we have a query or YAML config
    if 'yaml_config' in data:
        try:
            yaml_str = data['yaml_config']
            run_id = create_crawl_job_from_yaml(yaml_str)
            return jsonify({'id': run_id})
        except ValueError as e:
            return jsonify({'error': str(e)}), 400
    elif 'query' in data:
        # Get parameters
        query = data['query']
        max_depth = data.get('max_depth', 2)
        
        # Validate parameters
        if not query:
            return jsonify({'error': 'Query is required'}), 400
        if max_depth < 0 or max_depth > 5:
            return jsonify({'error': 'Max depth must be between 0 and 5'}), 400
            
        # Create job
        run_id = create_scrape_job(query, max_depth)
        
        return jsonify({'id': run_id})
    else:
        return jsonify({'error': 'Either query or yaml_config is required'}), 400

@api_bp.route('/runs/<int:run_id>/pause', methods=['POST'])
@limiter.limit(CONTROL_LIMIT)
def pause_run(run_id):
    """Pause a scrape run."""
    success = pause_scrape_job(run_id)
    if success:
        return jsonify({'status': 'paused'})
    else:
        return jsonify({'error': 'Failed to pause run'}), 400

@api_bp.route('/runs/<int:run_id>/resume', methods=['POST'])
@limiter.limit(CONTROL_LIMIT)
def resume_run(run_id):
    """Resume a paused scrape run."""
    success = resume_scrape_job(run_id)
    if success:
        return jsonify({'status': 'running'})
    else:
        return jsonify({'error': 'Failed to resume run'}), 400

@api_bp.route('/runs/<int:run_id>/stop', methods=['POST'])
@limiter.limit(CONTROL_LIMIT)
def stop_run(run_id):
    """Stop a scrape run."""
    success = stop_scrape_job(run_id)
    if success:
        return jsonify({'status': 'stopped'})
    else:
        return jsonify({'error': 'Failed to stop run'}), 400

@api_bp.route('/search', methods=['GET'])
@limiter.limit(SEARCH_LIMIT)
def search():
    """Search Bing for results."""
    # Get parameters
    query = request.args.get('q', '')
    num_results = request.args.get('limit', default=5, type=int)
    
    # Validate parameters
    if not query:
        return jsonify({'error': 'Query parameter q is required'}), 400
    if num_results < 1 or num_results > 20:
        return jsonify({'error': 'Limit must be between 1 and 20'}), 400
        
    # Search
    results = search_bing(query, num_results=num_results)
    
    return jsonify({
        'query': query,
        'results': results
    })

@api_bp.route('/vector-search', methods=['POST'])
@limiter.limit(SEARCH_LIMIT)
def vector_search():
    """Perform semantic search on stored documents."""
    data = request.json
    if not data or 'query' not in data:
        return jsonify({'error': 'Query is required'}), 400
        
    # Get parameters
    query = data['query']
    run_id = data.get('run_id')  # Optional: limit to specific run
    k = data.get('limit', 5)
    
    # Get vector store
    vector_store = get_vector_store()
    
    # Perform search
    search_results = vector_store.search(query, k=k)
    
    # Filter by run_id if specified
    if run_id is not None:
        search_results = [r for r in search_results if r['metadata'].get('run_id') == run_id]
    
    # Format results
    result = {
        'query': query,
        'results': search_results
    }
    
    return jsonify(result)

@api_bp.route('/structure-data', methods=['POST'])
def structure_data():
    """
    Use OpenAI or alternative to structure data from text.
    This is a placeholder for LLM-based schema parsing.
    """
    data = request.json
    if not data or 'text' not in data or 'schema' not in data:
        return jsonify({'error': 'Text and schema are required'}), 400
        
    # Get parameters
    text = data['text']
    schema = data['schema']
    
    # In a real implementation, this would call an LLM to parse the text
    # according to the schema. Here we just return a placeholder.
    result = {
        'structured_data': {
            'title': 'Extracted title would go here',
            'summary': 'This is a placeholder for LLM-extracted structured data.',
            'key_points': [
                'Would extract structured data based on schema',
                'Using LLM like DeepSeek, Claude or GPT',
                'Formatted according to provided schema'
            ]
        }
    }
    
    return jsonify(result)

@api_bp.route('/yaml-validator', methods=['POST'])
def validate_yaml():
    """Validate YAML configuration."""
    data = request.json
    if not data or 'yaml' not in data:
        return jsonify({'error': 'YAML is required'}), 400
        
    # Get YAML
    yaml_str = data['yaml']
    
    try:
        # Parse YAML
        config = yaml.safe_load(yaml_str)
        
        # Check required fields
        required_fields = ['start_urls']
        missing_fields = [field for field in required_fields if field not in config]
        
        if missing_fields:
            return jsonify({
                'valid': False,
                'error': f"Missing required fields: {', '.join(missing_fields)}"
            })
            
        return jsonify({
            'valid': True,
            'parsed_config': config
        })
        
    except Exception as e:
        return jsonify({
            'valid': False,
            'error': str(e)
        }), 400

# Error handlers

@api_bp.errorhandler(429)
def ratelimit_handler(e):
    return jsonify({
        'error': 'Rate limit exceeded',
        'message': str(e.description)
    }), 429

@api_bp.errorhandler(Exception)
def handle_exception(e):
    logger.error(f"API error: {str(e)}")
    return jsonify({
        'error': 'Server error',
        'message': str(e)
    }), 500