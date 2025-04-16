import logging
import time
import random
import os
import platform
from urllib.parse import urlparse, urljoin, urlunparse
from typing import Dict, Any, List, Tuple, Optional, Union
import json
import traceback
from pathlib import Path

from playwright.sync_api import sync_playwright, Page, Browser, BrowserContext, Response, Error as PlaywrightError

# Optional stealth mode - try to import but continue if not available
try:
    from playwright_stealth import stealth_sync
    STEALTH_MODE_AVAILABLE = True
except ImportError:
    STEALTH_MODE_AVAILABLE = False

logger = logging.getLogger(__name__)

# Default user agents by platform
DEFAULT_USER_AGENTS = {
    "Windows": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Darwin": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Linux": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
}

# Get appropriate user agent for current platform
DEFAULT_USER_AGENT = DEFAULT_USER_AGENTS.get(platform.system(), DEFAULT_USER_AGENTS["Linux"])

# Cache directory for saving cookies, content, etc.
CACHE_DIR = Path(os.path.expanduser("~/.cache/webintel"))
CACHE_DIR.mkdir(parents=True, exist_ok=True)


class BaseScraper:
    """
    Industry-ready web scraper with Playwright integration.
    
    Features:
    - Stealth mode to avoid bot detection
    - Proxy support
    - Cookie management
    - Screenshot and PDF capabilities
    - Configurable retry mechanism
    - Resource blocking for performance
    - Request interception
    - Human-like scrolling and interaction
    - Error recovery strategies
    """
    
    def __init__(self, 
                 headless: bool = True, 
                 proxy: Optional[str] = None, 
                 user_agent: Optional[str] = None,
                 timeout: int = 60000000,
                 retry_attempts: int = 5,
                 retry_delay: int = 20000,
                 cache_cookies: bool = True,
                 block_resources: Optional[List[str]] = None,
                 ignore_https_errors: bool = True,
                 cache_responses: bool = False,
                 slow_mo: int = 26,
                 viewport: Dict[str, int] = None,
                 cookies_path: Optional[str] = None):
        """
        Initialize the scraper with customizable options.
        """
        self.headless = headless
        self.proxy = proxy
        self.user_agent = user_agent or DEFAULT_USER_AGENT
        self.timeout = timeout
        self.retry_attempts = retry_attempts
        self.retry_delay = retry_delay
        self.cache_cookies = cache_cookies
        self.block_resources = block_resources or []
        self.ignore_https_errors = ignore_https_errors
        self.cache_responses = cache_responses
        self.slow_mo = slow_mo
        self.viewport = viewport or {"width": 1920, "height": 1080}
        
        # Cookie storage path
        self.cookies_path = cookies_path
        if self.cache_cookies and not self.cookies_path:
            self.cookies_path = str(CACHE_DIR / "cookies.json")
        
        # Cache for response data
        self.response_cache = {}
        
        # Stats for monitoring
        self.stats = {
            "pages_accessed": 0,
            "bytes_downloaded": 0,
            "total_requests": 0,
            "failed_requests": 0,
            "retry_count": 0
        }

    def get_page_content(self, 
                        url: str, 
                        wait_for_selectors: Optional[List[str]] = None,
                        wait_for_load: bool = True,
                        use_stealth: bool = True,
                        save_screenshots: bool = False,
                        scroll_behavior: Optional[str] = None,
                        emulate_device: Optional[str] = None,
                        cookies: Optional[List[Dict]] = None,
                        js_snippets: Optional[List[str]] = None,
                        block_urls: Optional[List[str]] = None) -> Tuple[Optional[str], Dict[str, Any]]:
        """
        Fetch HTML content from a URL using Playwright with extensive options.
        """
        browser = None
        context = None
        page = None
        
        # Check if response is cached
        if self.cache_responses and url in self.response_cache:
            logger.info(f"Using cached response for {url}")
            return self.response_cache[url]
        
        metadata = {
            "url": url,
            "status": None,
            "title": None,
            "error": None,
            "timestamp": time.time(),
            "content_type": None,
            "headers": None,
            "screenshot_path": None,
            "cookies": None
        }
        
        for attempt in range(self.retry_attempts + 1):
            try:
                with sync_playwright() as p:
                    # Setup browser launch options (do not pass ignore_https_errors here)
                    browser_args = {
                        "headless": self.headless,
                        "slow_mo": self.slow_mo
                    }
                    
                    # Add proxy if configured
                    if self.proxy:
                        browser_args["proxy"] = {
                            "server": self.proxy
                        }
                    
                    # Launch browser with custom args to improve stealth
                    browser = p.chromium.launch(**browser_args)
                    
                    # Create new context with custom settings (pass ignore_https_errors here)
                    context_options = {
                        "user_agent": self.user_agent,
                        "viewport": self.viewport,
                        "ignore_https_errors": self.ignore_https_errors
                    }
                    
                    # Add device emulation if specified
                    if emulate_device:
                        device = getattr(p.devices, emulate_device, None)
                        if device:
                            context_options.update(device)
                        else:
                            logger.warning(f"Device {emulate_device} not found, using default settings")
                    
                    context = browser.new_context(**context_options)
                    
                    # Load cookies from disk if caching is enabled
                    if self.cache_cookies and os.path.exists(self.cookies_path):
                        try:
                            with open(self.cookies_path, 'r') as f:
                                cookies_data = json.load(f)
                                context.add_cookies(cookies_data)
                                logger.debug(f"Loaded {len(cookies_data)} cookies from {self.cookies_path}")
                        except Exception as e:
                            logger.warning(f"Error loading cookies: {str(e)}")
                    
                    # Add custom cookies if provided
                    if cookies:
                        context.add_cookies(cookies)
                    
                    # Create new page
                    page = context.new_page()
                    
                    # Setup request interception for resource blocking
                    if self.block_resources or block_urls:
                        async def route_handler(route, request):
                            if self.block_resources and request.resource_type in self.block_resources:
                                await route.abort()
                                return
                            if block_urls and any(pattern in request.url for pattern in block_urls):
                                await route.abort()
                                return
                            await route.continue_()
                        page.route("**/*", route_handler)
                    
                    # Apply stealth mode if available and requested
                    if use_stealth and STEALTH_MODE_AVAILABLE:
                        try:
                            stealth_sync(page)
                            logger.debug("Stealth mode applied successfully")
                        except Exception as e:
                            logger.warning(f"Failed to apply stealth mode: {str(e)}")
                            self._apply_manual_stealth(page)
                    elif use_stealth:
                        self._apply_manual_stealth(page)
                    
                    # Setup response handler to collect metadata
                    response = None
                    def handle_response(resp):
                        nonlocal response
                        if resp.url == url:
                            response = resp
                    page.on("response", handle_response)
                    
                    logger.info(f"Navigating to {url} (attempt {attempt+1}/{self.retry_attempts+1})")
                    response = page.goto(url, timeout=self.timeout, wait_until="domcontentloaded")
                    
                    if not response:
                        logger.warning(f"No response received for {url}")
                        raise PlaywrightError("No response received")
                    
                    status = response.status
                    metadata["status"] = status
                    
                    if status >= 400:
                        logger.warning(f"Received status code {status} for {url}")
                        if attempt < self.retry_attempts:
                            logger.info(f"Retrying in {self.retry_delay}ms...")
                            time.sleep(self.retry_delay / 1000)
                            self.stats["retry_count"] += 1
                            continue
                        else:
                            metadata["error"] = f"HTTP Status {status}"
                            return None, metadata
                    
                    if wait_for_load:
                        page.wait_for_load_state('networkidle', timeout=self.timeout)
                    
                    if wait_for_selectors:
                        for selector in wait_for_selectors:
                            try:
                                page.wait_for_selector(selector, timeout=self.timeout)
                                logger.debug(f"Selector '{selector}' found")
                            except Exception as e:
                                logger.warning(f"Selector '{selector}' not found: {str(e)}")
                    
                    if js_snippets:
                        for script in js_snippets:
                            try:
                                page.evaluate(script)
                            except Exception as e:
                                logger.warning(f"Error executing JavaScript: {str(e)}")
                    
                    if scroll_behavior:
                        self._scroll_page(page, behavior=scroll_behavior)
                    
                    if save_screenshots:
                        screenshot_path = str(CACHE_DIR / f"screenshot_{int(time.time())}.png")
                        page.screenshot(path=screenshot_path, full_page=True)
                        metadata["screenshot_path"] = screenshot_path
                    
                    html = page.content()
                    
                    metadata.update({
                        "title": page.title(),
                        "url": page.url,
                        "content_type": response.headers.get("content-type", None),
                        "headers": dict(response.headers),
                        "cookies": context.cookies()
                    })
                    
                    if self.cache_cookies:
                        try:
                            with open(self.cookies_path, 'w') as f:
                                json.dump(context.cookies(), f)
                        except Exception as e:
                            logger.warning(f"Error saving cookies: {str(e)}")
                    
                    self.stats["pages_accessed"] += 1
                    self.stats["bytes_downloaded"] += len(html)
                    self.stats["total_requests"] += 1
                    
                    if self.cache_responses:
                        self.response_cache[url] = (html, metadata)
                    
                    page.close()
                    context.close()
                    browser.close()
                    
                    return html, metadata
                    
            except Exception as e:
                if browser:
                    try:
                        if page:
                            page.close()
                        if context:
                            context.close()
                        browser.close()
                    except:
                        pass
                
                error_details = str(e)
                logger.error(f"Error scraping {url}: {error_details}")
                self.stats["failed_requests"] += 1
                
                if attempt < self.retry_attempts:
                    retry_delay = self.retry_delay * (2 ** attempt)
                    logger.info(f"Retrying in {retry_delay/1000}s... (attempt {attempt+1}/{self.retry_attempts})")
                    time.sleep(retry_delay / 1000)
                    self.stats["retry_count"] += 1
                    continue
                else:
                    metadata["error"] = error_details
                    return None, metadata
        
        return None, metadata
    
    def _apply_manual_stealth(self, page: Page):
        """Apply manual stealth techniques when stealth_sync is not available."""
        try:
            page.evaluate("""
                Object.defineProperty(navigator, 'webdriver', { get: () => false });
                window.navigator.permissions.query = (parameters) => {
                    return Promise.resolve({ state: 'granted' });
                };
                Object.defineProperty(navigator, 'plugins', {
                    get: () => [1, 2, 3, 4, 5].map(() => {
                        return {
                            0: { type: "application/x-google-chrome-pdf" },
                            description: "Portable Document Format",
                            filename: "internal-pdf-viewer",
                            length: 1,
                            name: "Chrome PDF Plugin"
                        }
                    })
                });
                Object.defineProperty(navigator, 'language', { get: () => 'en-US' });
                Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
            """)
            logger.debug("Applied manual stealth techniques")
        except Exception as e:
            logger.warning(f"Failed to apply manual stealth techniques: {str(e)}")
    
    def _scroll_page(self, page: Page, behavior: str = 'smooth', max_scrolls: int = 10, scroll_delay: int = 1000):
        """Perform scrolling behavior to mimic human browsing."""
        try:
            page_height = page.evaluate("() => document.body.scrollHeight")
            viewport_height = page.evaluate("() => window.innerHeight")
            num_scrolls = min(max_scrolls, max(1, int(page_height / viewport_height)))
            
            for i in range(num_scrolls):
                scroll_amount = viewport_height * random.uniform(0.7, 0.9)
                page.evaluate(f"""
                    window.scrollBy({{
                        top: {scroll_amount},
                        left: 0,
                        behavior: '{behavior}'
                    }});
                """)
                time.sleep(scroll_delay / 1000 * random.uniform(0.8, 1.2))
                if random.random() < 0.2:
                    jitter_amount = random.randint(-20, 20)
                    page.evaluate(f"window.scrollBy({{ top: 0, left: {jitter_amount}, behavior: '{behavior}' }});")
            
            if random.random() < 0.3:
                up_amount = random.uniform(0.2, 0.6) * page_height
                page.evaluate(f"window.scrollBy({{ top: -{up_amount}, left: 0, behavior: '{behavior}' }});")
                time.sleep(scroll_delay / 1000 * random.uniform(0.5, 1.0))
            
            logger.debug(f"Completed {num_scrolls} scrolls")
                
        except Exception as e:
            logger.warning(f"Error during page scrolling: {str(e)}")
    
    def save_as_pdf(self, url: str, output_path: str) -> bool:
        """
        Save page as PDF.
        """
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto(url, wait_until="networkidle")
                page.pdf(path=output_path, format="A4")
                browser.close()
                return True
        except Exception as e:
            logger.error(f"Error saving PDF: {str(e)}")
            return False
    
    def extract_content_with_js(self, url: str, js_script: str) -> Any:
        """
        Extract content using a custom JavaScript function.
        """
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=self.headless)
                page = browser.new_page(user_agent=self.user_agent)
                page.goto(url, wait_until="networkidle")
                result = page.evaluate(js_script)
                browser.close()
                return result
        except Exception as e:
            logger.error(f"Error extracting content with JS: {str(e)}")
            return None
    
    def get_stats(self) -> Dict[str, Any]:
        """Get scraper statistics."""
        return self.stats
    
    def clear_cache(self):
        """Clear response cache."""
        self.response_cache = {}
        logger.info("Response cache cleared")
    
    @staticmethod
    def get_domain(url: str) -> str:
        """Extract the domain from a URL."""
        parsed_url = urlparse(url)
        return parsed_url.netloc
        
    @staticmethod
    def normalize_url(url: str, base_url: Optional[str] = None) -> Optional[str]:
        """Normalize a URL, resolving relative URLs if base_url is provided."""
        if not url:
            return None
        if base_url and not url.startswith(('http://', 'https://')):
            url = urljoin(base_url, url)
        parsed = urlparse(url)
        if parsed.fragment:
            parsed = parsed._replace(fragment='')
        if not parsed.scheme:
            parsed = parsed._replace(scheme='https')
        query = parsed.query
        if query:
            from urllib.parse import parse_qs, urlencode
            params = parse_qs(query)
            for param in ['utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content', 'fbclid', 'gclid']:
                if param in params:
                    del params[param]
            new_query = urlencode(params, doseq=True)
            parsed = parsed._replace(query=new_query)
        return urlunparse(parsed)


# Helper function for simpler API
def get_page_content(url: str, 
                    wait_for_selectors: Optional[List[str]] = None, 
                    headless: bool = True, 
                    proxy: Optional[str] = None,
                    use_stealth: bool = True) -> Tuple[Optional[str], Dict[str, Any]]:
    """
    Simple helper function to get page content without creating a BaseScraper instance.
    """
    scraper = BaseScraper(headless=headless, proxy=proxy)
    return scraper.get_page_content(
        url, 
        wait_for_selectors=wait_for_selectors,
        use_stealth=use_stealth
    )
