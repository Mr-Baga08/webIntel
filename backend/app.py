import os
import logging
from datetime import datetime
from flask import Flask, render_template, request, jsonify, redirect, url_for, g
from flask_cors import CORS

from .api.endpoints import api_bp
from .api.enhanced_endpoints import enhanced_bp  # Import enhanced content endpoints
from .api.limiter import limiter
from .db.init_db import init_db, get_db
from .scheduler import start_scheduler, shutdown_scheduler
from .scheduler_enhanced import extend_scheduler  # Import enhanced scheduler extension
from .models import ScrapeRun, ScrapedPage

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

# Track scheduler state
scheduler_running = False

def create_app(test_config=None):
    global scheduler_running
    
    # Create and configure the app
    app = Flask(__name__, instance_relative_config=True)
    
    # Load config
    app.config.from_mapping(
        SECRET_KEY=os.environ.get('SECRET_KEY', 'dev'),
        DATABASE_URL=os.environ.get('DATABASE_URL', 'sqlite:///webintel.db'),
    )
    
    if test_config is None:
        # Load the instance config, if it exists, when not testing
        app.config.from_pyfile('config.py', silent=True)
    else:
        # Load the test config if passed in
        app.config.from_mapping(test_config)
        
    # Initialize CORS
    CORS(app)
    
    # Initialize rate limiter
    limiter.init_app(app)
    
    # Register blueprints
    app.register_blueprint(api_bp)
    app.register_blueprint(enhanced_bp)  # Register enhanced blueprint
    
    # Initialize database
    with app.app_context():
        init_db()
        logger.info("Database initialized")
    
    # Register CLI commands
    @app.cli.command('init-db')
    def init_db_command():
        """Initialize the database."""
        init_db()
        logger.info('Initialized the database.')
    
    # Define routes
    @app.route('/')
    def index():
        """Render the dashboard."""
        # Start scheduler on first request if not already running
        global scheduler_running
        if not scheduler_running:
            try:
                logger.info("Starting scheduler from first request")
                start_scheduler()
                scheduler_running = True
            except Exception as e:
                logger.error(f"Failed to start scheduler: {str(e)}")
                
        return render_template('index.html')
    
    @app.route('/runs/<int:run_id>')
    def run_detail(run_id):
        """Render the run detail page."""
        return render_template('run_detail.html', run_id=run_id)
    
    @app.route('/enhanced')
    def enhanced_dashboard():
        """Render the enhanced content dashboard."""
        return render_template('enhanced_dashboard.html')
    
    @app.route('/enhanced/runs/<int:run_id>')
    def enhanced_run_detail(run_id):
        """Render the enhanced content run detail page."""
        return render_template('enhanced_run_detail.html', run_id=run_id)
    
    # Domain-specific content pages
    @app.route('/enhanced/<domain>')
    def domain_dashboard(domain):
        """Render the domain-specific dashboard."""
        valid_domains = ['marketing', 'legal', 'academic', 'technical']
        if domain not in valid_domains:
            return redirect(url_for('enhanced_dashboard'))
            
        return render_template('domain_dashboard.html', domain=domain)
    
    # Start the scheduler during app creation
    if not scheduler_running:
        try:
            logger.info("Starting scheduler during app creation")
            start_scheduler()
            scheduler_running = True
        except Exception as e:
            logger.error(f"Failed to start scheduler during app creation: {str(e)}")
    
    # Shutdown scheduler when app stops
    @app.teardown_appcontext
    def shutdown_app_scheduler(exception=None):
        global scheduler_running
        # Only shutdown when the app is truly shutting down, not on regular requests
        if hasattr(g, '_app_shutting_down') and g._app_shutting_down and scheduler_running:
            try:
                logger.info("Shutting down scheduler")
                shutdown_scheduler()
                scheduler_running = False
            except Exception as e:
                logger.warning(f"Error shutting down scheduler: {str(e)}")
                scheduler_running = False
    
    # Register a signal handler to know when the app is truly shutting down
    import atexit
    def on_app_shutdown():
        # Set a flag that can be checked in teardown_appcontext
        g._app_shutting_down = True
        global scheduler_running
        if scheduler_running:
            try:
                logger.info("Shutting down scheduler during app shutdown")
                shutdown_scheduler()
                scheduler_running = False
            except Exception as e:
                logger.warning(f"Error shutting down scheduler during app shutdown: {str(e)}")
                scheduler_running = False
    
    atexit.register(on_app_shutdown)
    
    # Create a special endpoint to process pending jobs manually
    @app.route('/api/admin/process-pending', methods=['POST'])
    def process_pending_jobs():
        """Manually trigger processing of pending jobs."""
        try:
            db = next(get_db())
            try:
                pending_runs = db.query(ScrapeRun).filter(ScrapeRun.status == 'pending').all()
                for run in pending_runs:
                    run.status = 'running'
                    run.updated_at = datetime.utcnow()
                db.commit()
                return jsonify({"success": True, "message": f"Updated {len(pending_runs)} pending jobs"})
            finally:
                db.close()
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
    
    return app

# Create app
app = create_app()

if __name__ == '__main__':
    # Run app
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)