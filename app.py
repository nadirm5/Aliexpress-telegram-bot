# -*- coding: utf-8 -*-
import logging
import os
import re
import json
import asyncio
import time
import aiohttp
from datetime import datetime, timedelta
from dotenv import load_dotenv
from urllib.parse import urlparse, urlunparse, urlencode
import iop
from concurrent.futures import ThreadPoolExecutor
from aliexpress_utils import get_product_details_by_id 

# Telegram imports
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, JobQueue 
from telegram.constants import ParseMode, ChatAction

# Initialize logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

# Resolve the short link to the full AliExpress product URL
async def resolve_short_link(url: str, session: aiohttp.ClientSession) -> str:
    """Resolve the short link to the full AliExpress product URL."""
    try:
        async with session.head(url, allow_redirects=True) as response:
            # Return the final URL after redirection
            return str(response.url)
    except Exception as e:
        logger.error(f"Error resolving short link {url}: {e}")
        return None

# rest of the code follows...

# --- Environment Variable Loading ---
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
ALIEXPRESS_APP_KEY = os.getenv('ALIEXPRESS_APP_KEY')
ALIEXPRESS_APP_SECRET = os.getenv('ALIEXPRESS_APP_SECRET')
TARGET_CURRENCY = os.getenv('TARGET_CURRENCY', 'USD')
TARGET_LANGUAGE = os.getenv('TARGET_LANGUAGE', 'ar')
QUERY_COUNTRY = os.getenv('QUERY_COUNTRY', 'US')
ALIEXPRESS_TRACKING_ID = os.getenv('ALIEXPRESS_TRACKING_ID', 'default')

# --- Basic Logging Setup ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)

# --- AliExpress API Configuration ---
ALIEXPRESS_API_URL = 'https://api-sg.aliexpress.com/sync'
QUERY_FIELDS = 'product_main_image_url,target_sale_price,product_title,target_sale_price_currency'

# Thread pool for blocking API calls
executor = ThreadPoolExecutor(max_workers=10)

# --- Cache Configuration ---
CACHE_EXPIRY_DAYS = 1
CACHE_EXPIRY_SECONDS = CACHE_EXPIRY_DAYS * 24 * 60 * 60

# --- Environment Variable Validation ---
if not all([TELEGRAM_BOT_TOKEN, ALIEXPRESS_APP_KEY, ALIEXPRESS_APP_SECRET, ALIEXPRESS_TRACKING_ID]):
    logger.error("Error: Missing required environment variables. Check TELEGRAM_BOT_TOKEN, ALIEXPRESS_*, TRACKING_ID.")
    exit()

# --- Initialize AliExpress API Client ---
try:
    aliexpress_client = iop.IopClient(ALIEXPRESS_API_URL, ALIEXPRESS_APP_KEY, ALIEXPRESS_APP_SECRET)
    logger.info("AliExpress API client initialized.")
except Exception as e:
    logger.exception(f"Error initializing AliExpress API client: {e}")
    logger.error("Check API URL and credentials.")
    exit()

# --- Regex Optimization: Precompile patterns ---

URL_REGEX = re.compile(r'https?://[^\s<>"]+|www\.[^\s<>"]+|\b(?:s\.click\.|a\.)?aliexpress\.(?:com|ru|es|fr|pt|it|pl|nl|co\.kr|co\.jp|com\.br|com\.tr|com\.vn|us|id|th|ar)(?:\.[\w-]+)?/[^\s<>"]*', re.IGNORECASE)
PRODUCT_ID_REGEX = re.compile(r'/item/(\d+)\.html')
STANDARD_ALIEXPRESS_DOMAIN_REGEX = re.compile(r'https?://(?!a\.|s\.click\.)([\w-]+\.)?aliexpress\.(com|ru|es|fr|pt|it|pl|nl|co\.kr|co\.jp|com\.br|com\.tr|com\.vn|us|id\.aliexpress\.com|th\.aliexpress\.com|ar\.aliexpress\.com)(\.([\w-]+))?(/.*)?', re.IGNORECASE)
SHORT_LINK_DOMAIN_REGEX = re.compile(r'https?://(?:s\.click\.aliexpress\.com/e/|a\.aliexpress\.com/_)[a-zA-Z0-9_-]+/?', re.IGNORECASE)


# --- Offer Parameter Mapping ---
OFFER_PARAMS = {
    "coin_page": {  "name": "💰 التخفيض بالعملات فالصفحة", "params": { "sourceType": "coin_page","afSmartRedirect": "y","tracking_id": ALIEXPRESS_TRACKING_ID}},
    "coin": {"name": "🪙 تخفيض العملات", "params": {"sourceType": "620%26channel=coin" , "afSmartRedirect": "y"}},
    "super": {"name": "🔥 السوبر ديلز", "params": {"sourceType": "562", "channel": "sd" , "afSmartRedirect": "y"}},
    "limited": {"name": "⏳ العرض المحدود", "params": {"sourceType": "561", "channel": "limitedoffers" , "afSmartRedirect": "y"}},
    "bigsave": {"name": "💰 التخفيض الكبير", "params": {"sourceType": "680", "channel": "bigSave" , "afSmartRedirect": "y"}},
}
OFFER_ORDER = ["coin", "super", "limited", "bigsave"]

# --- Cache Implementation with Expiry ---
class CacheWithExpiry:
    def __init__(self, expiry_seconds):
        self.cache = {}
        self.expiry_seconds = expiry_seconds
        self._lock = asyncio.Lock()

    async def get(self, key):
        """Get item from cache if it exists and is not expired (async safe)"""
        async with self._lock:
            if key in self.cache:
                item, timestamp = self.cache[key]
                if time.time() - timestamp < self.expiry_seconds:
                    logger.debug(f"Cache hit for key: {key}")
                    return item
                else:
                    logger.debug(f"Cache expired for key: {key}")
                    del self.cache[key]
            logger.debug(f"Cache miss for key: {key}")
            return None

    async def set(self, key, value):
        """Add item to cache with current timestamp (async safe)"""
        async with self._lock:
            self.cache[key] = (value, time.time())
            logger.debug(f"Cached value for key: {key}")

    async def clear_expired(self):
        """Remove all expired items from cache (async safe)"""
        async with self._lock:
            current_time = time.time()
            expired_keys = [k for k, (_, t) in self.cache.items()
                            if current_time - t >= self.expiry_seconds]
            count = 0
            for key in expired_keys:
                try:
                    del self.cache[key]
                    count += 1
                except KeyError:
                    pass
            return count

# Initialize caches
product_cache = CacheWithExpiry(CACHE_EXPIRY_SECONDS)
link_cache = CacheWithExpiry(CACHE_EXPIRY_SECONDS)
resolved_url_cache = CacheWithExpiry(CACHE_EXPIRY_SECONDS)

# --- Helper Functions ---

async def resolve_short_link(short_url: str, session: aiohttp.ClientSession) -> str | None:
    """Follows redirects for a short URL to find the final destination URL."""
    cached_final_url = await resolved_url_cache.get(short_url)
    if cached_final_url:
        logger.info(f"Cache hit for resolved short link: {short_url} -> {cached_final_url}")
        return cached_final_url

    logger.info(f"Resolving short link: {short_url}")
    try:
        async with session.get(short_url, allow_redirects=True, timeout=10) as response:
            if response.status == 200 and response.url:
                final_url = str(response.url)
                logger.info(f"Resolved {short_url} to {final_url}")
                
                if '.aliexpress.us' in final_url:
                    logger.info(f"Detected US domain in {final_url}, converting to .com domain")
                    final_url = final_url.replace('.aliexpress.us', '.aliexpress.com')
                    logger.info(f"Converted URL: {final_url}")
                
                # Replace _randl_shipto=US with _randl_shipto=QUERY_COUNTRY
                if '_randl_shipto=' in final_url:
                    logger.info(f"Found _randl_shipto parameter in URL, replacing with QUERY_COUNTRY value")
                    final_url = re.sub(r'_randl_shipto=[^&]+', f'_randl_shipto={QUERY_COUNTRY}', final_url)
                    logger.info(f"Updated URL with correct country: {final_url}")
                    
                    # Re-fetch the URL with the updated country parameter to get the correct product ID
                    try:
                        logger.info(f"Re-fetching URL with updated country parameter: {final_url}")
                        async with session.get(final_url, allow_redirects=True, timeout=10) as country_response:
                            if country_response.status == 200 and country_response.url:
                                final_url = str(country_response.url)
                                logger.info(f"Re-fetched URL with correct country: {final_url}")
                    except Exception as e:
                        logger.warning(f"Error re-fetching URL with updated country parameter: {e}")
                
                # Extract product ID after domain conversion to ensure we get the correct ID
                product_id = extract_product_id(final_url)
                if STANDARD_ALIEXPRESS_DOMAIN_REGEX.match(final_url) and product_id:
                    # Re-fetch product details with the new product ID if domain was changed
                    logger.info(f"Using product ID {product_id} from converted URL")
                    await resolved_url_cache.set(short_url, final_url)
                    return final_url
                else:
                    logger.warning(f"Resolved URL {final_url} doesn't look like a valid AliExpress product page.")
                    return None
            else:
                logger.error(f"Failed to resolve short link {short_url}. Status: {response.status}")
                return None
    except asyncio.TimeoutError:
        logger.error(f"Timeout resolving short link: {short_url}")
        return None
    except aiohttp.ClientError as e:
        logger.error(f"HTTP ClientError resolving short link {short_url}: {e}")
        return None
    except Exception as e:
        logger.exception(f"Unexpected error resolving short link {short_url}: {e}")
        return None


def extract_product_id(url):
    """Extracts the product ID from an AliExpress URL.
    Handles different domain formats including .us domain.
    """
    # First, ensure we're working with a standardized URL format
    # Convert .us domain to .com domain if needed
    if '.aliexpress.us' in url:
        url = url.replace('.aliexpress.us', '.aliexpress.com')
        logger.info(f"Converted .us URL to .com format for product ID extraction: {url}")
    
    # Try standard product ID extraction
    match = PRODUCT_ID_REGEX.search(url)
    if match:
        return match.group(1)
    
    # If standard extraction fails, try alternative patterns that might be used in different domains
    # Some domains might use different URL structures
    alt_patterns = [
        r'/p/[^/]+/([0-9]+)\.html',  # Alternative pattern sometimes used
        r'product/([0-9]+)'
    ]
    
    for pattern in alt_patterns:
        alt_match = re.search(pattern, url)
        if alt_match:
            product_id = alt_match.group(1)
            logger.info(f"Extracted product ID {product_id} using alternative pattern {pattern}")
            return product_id
    
    logger.warning(f"Could not extract product ID from URL: {url}")
    return None

# Renamed from extract_valid_aliexpress_urls_with_ids
def extract_potential_aliexpress_urls(text):
    """Finds potential AliExpress URLs (standard and short) in text using regex."""
    return URL_REGEX.findall(text)


def clean_aliexpress_url(url: str, product_id: str) -> str | None:
    """Reconstructs a clean base URL (scheme, domain, path) for a given product ID."""
    try:
        parsed_url = urlparse(url)
        # Ensure the path segment is correct for the product ID
        path_segment = f'/item/{product_id}.html'
        base_url = urlunparse((
            parsed_url.scheme or 'https',
            parsed_url.netloc,
            path_segment,
            '', '', ''
        ))
        return base_url
    except ValueError:
        logger.warning(f"Could not parse or reconstruct URL: {url}")
        return None


def build_url_with_offer_params(base_url, params_to_add):
    """Adds offer parameters to a base URL."""
    if not params_to_add:
        return base_url

    try:
        parsed_url = urlparse(base_url)
        
        # Remove country subdomain (like 'ar.', 'es.', etc.) from netloc
        netloc = parsed_url.netloc
        if '.' in netloc and netloc.count('.') > 1:
            # Extract domain parts
            parts = netloc.split('.')
            # Keep only the main domain (aliexpress.com)
            if len(parts) >= 2 and 'aliexpress' in parts[-2]:
                netloc = f"aliexpress.{parts[-1]}"
        
        # Special handling for sourceType parameter that contains encoded '&'
        if 'sourceType' in params_to_add and '%26' in params_to_add['sourceType']:
            # The parameter already contains encoded values, use it directly
            new_query_string = '&'.join([f"{k}={v}" for k, v in params_to_add.items() if k != 'channel' and '%26channel=' in params_to_add['sourceType']])
        else:
            new_query_string = urlencode(params_to_add)
            
        # Reconstruct URL ensuring path is preserved correctly
        reconstructed_url = urlunparse((
            parsed_url.scheme,
            netloc,
            parsed_url.path,
            '',
            new_query_string,
            ''
        ))
        # Add the star.aliexpress.com prefix to the reconstructed URL
        reconstructed_url = f"https://star.aliexpress.com/share/share.htm?&redirectUrl={reconstructed_url}"
        return reconstructed_url
    except ValueError:
        logger.error(f"Error building URL with params for base: {base_url}")
        return base_url


# --- Maintenance Task ---
async def periodic_cache_cleanup(context: ContextTypes.DEFAULT_TYPE):
    """Periodically clean up expired cache items (Job Queue callback)"""
    try:
        product_expired = await product_cache.clear_expired()
        link_expired = await link_cache.clear_expired()
        resolved_expired = await resolved_url_cache.clear_expired()
        logger.info(f"Cache cleanup: Removed {product_expired} product, {link_expired} link, {resolved_expired} resolved URL items.")
        logger.info(f"Cache stats: {len(product_cache.cache)} products, {len(link_cache.cache)} links, {len(resolved_url_cache.cache)} resolved URLs in cache.")
    except Exception as e:
        logger.error(f"Error in periodic cache cleanup job: {e}")
def build_url_with_offer_params(base_url, params_to_add):
    """Adds offer parameters to a base URL. Handles 'coin_page' offer type."""
    if not params_to_add:
        return base_url

    try:
        parsed_url = urlparse(base_url)
        
        # Special handling for coin page offer
        if params_to_add.get('sourceType') == 'coin_page':
            product_id = extract_product_id(base_url)
            if not product_id:
                logger.warning(f"Could not extract product ID for coin page from URL: {base_url}")
                return None
            
            # Generate random parameters
            random_fcid = generate_random_fcid()
            random_trace_key = generate_random_trace_key()
            terminal_id = generate_terminal_id()
            
            # Build the special coin page URL
            coin_page_url = (
                "https://m.aliexpress.com/p/coin-index/index.html"
                "?_immersiveMode=true"
                "&from=syicon"
                f"&productIds={product_id}"
                f"&aff_fcid={random_fcid}"
                "&aff_fsk=_ooGaZvh"
                "&aff_platform=api-new-link-generate"
                "&sk=_ooGaZvh"
                f"&aff_trace_key={random_trace_key}"
                f"&terminal_id={terminal_id}"
            )
            logger.info(f"Generated coin page URL: {coin_page_url}")
            return coin_page_url
        
        # Original handling for other offer types
        netloc = parsed_url.netloc
        if '.' in netloc and netloc.count('.') > 1:
            parts = netloc.split('.')
            if len(parts) >= 2 and 'aliexpress' in parts[-2]:
                netloc = f"aliexpress.{parts[-1]}"
        
        if 'sourceType' in params_to_add and '%26' in params_to_add['sourceType']:
            new_query_string = '&'.join([f"{k}={v}" for k, v in params_to_add.items() if k != 'channel' and '%26channel=' in params_to_add['sourceType']])
        else:
            new_query_string = urlencode(params_to_add)
        
        reconstructed_url = urlunparse((
            parsed_url.scheme,
            netloc,
            parsed_url.path,
            '',
            new_query_string,
            ''
        ))
        reconstructed_url = f"https://star.aliexpress.com/share/share.htm?&redirectUrl={reconstructed_url}"
        return reconstructed_url
    except ValueError:
        logger.error(f"Error building URL with params for base: {base_url}")
        return base_url
# --- Maintenance Task ---
async def periodic_cache_cleanup(context: ContextTypes.DEFAULT_TYPE):
    """Periodically clean up expired cache items (Job Queue callback)"""
    try:
        product_expired = await product_cache.clear_expired()
        link_expired = await link_cache.clear_expired()
        resolved_expired = await resolved_url_cache.clear_expired()
        logger.info(f"Cache cleanup: Removed {product_expired} product, {link_expired} link, {resolved_expired} resolved URL items.")
        logger.info(f"Cache stats: {len(product_cache.cache)} products, {len(link_cache.cache)} links, {len(resolved_url_cache.cache)} resolved URLs in cache.")
    except Exception as e:
        logger.error(f"Error in periodic cache cleanup job: {e}")

# --- API Call Functions (Adapted for Async Cache) ---

async def fetch_product_details_v2(product_id):
    """Fetches product details using aliexpress.affiliate.productdetail.get with async cache."""
    cached_data = await product_cache.get(product_id)
    if cached_data:
        logger.info(f"Cache hit for product ID: {product_id}")
        return cached_data

    logger.info(f"Fetching product details for ID: {product_id}")

    def _execute_api_call():
        """Execute blocking API call in a thread pool."""
        try:
            request = iop.IopRequest('aliexpress.affiliate.productdetail.get')
            request.add_api_param('fields', QUERY_FIELDS)
            request.add_api_param('product_ids', product_id)
            request.add_api_param('target_currency', TARGET_CURRENCY)
            request.add_api_param('target_language', TARGET_LANGUAGE)
            request.add_api_param('tracking_id', ALIEXPRESS_TRACKING_ID)
            request.add_api_param('country', QUERY_COUNTRY)

            return aliexpress_client.execute(request)
        except Exception as e:
            logger.error(f"Error in API call thread for product {product_id}: {e}")
            return None

    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(executor, _execute_api_call)

    if not response or not response.body:
        logger.error(f"Product detail API call failed or returned empty body for ID: {product_id}")
        return None

    try:
        response_data = response.body
        # Handle potential non-JSON string response (though SDK should return structured)
        if isinstance(response_data, str):
            try:
                response_data = json.loads(response_data)
            except json.JSONDecodeError as json_err:
                logger.error(f"Failed to decode JSON response for product {product_id}: {json_err}. Response: {response_data[:500]}")
                return None

        if 'error_response' in response_data:
            error_details = response_data.get('error_response', {})
            error_msg = error_details.get('msg', 'Unknown API error')
            error_code = error_details.get('code', 'N/A')
            logger.error(f"API Error for Product ID {product_id}: Code={error_code}, Msg={error_msg}")
            return None

        detail_response = response_data.get('aliexpress_affiliate_productde
