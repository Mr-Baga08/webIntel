from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Create rate limiter
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"]
)

# Define rate limits for specific endpoints (use strings not lists)
SCRAPE_LIMIT = "10 per hour;50 per day"
SEARCH_LIMIT = "30 per hour;300 per day"
CONTROL_LIMIT = "60 per hour"  # Higher limit for control operations