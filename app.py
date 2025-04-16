# -*- coding: utf-8 -*-
import logging
import os
import re
import json
import asyncio
import time
from datetime import datetime, timedelta
import aiohttp  
from dotenv import load_dotenv
from urllib.parse import urlparse, urlunparse, urlencode
import iop
from concurrent.futures import ThreadPoolExecutor
from aliexpress_utils import get_product_details_by_id 

# Telegram imports
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, JobQueue 
from telegram.constants import ParseMode, ChatAction


# --- Environment Variable Loading ---
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
ALIEXPRESS_APP_KEY = os.getenv('ALIEXPRESS_APP_KEY')
ALIEXPRESS_APP_SECRET = os.getenv('ALIEXPRESS_APP_SECRET')
TARGET_CURRENCY = os.getenv('TARGET_CURRENCY', 'USD')
TARGET_LANGUAGE = os.getenv('TARGET_LANGUAGE', 'en')
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
    "coin": {"name": "🪙 Coin", "params": {"sourceType": "620", "channel": "coin" , "afSmartRedirect": "y"}},
    "super": {"name": "🔥 Super Deals", "params": {"sourceType": "562", "channel": "sd" , "afSmartRedirect": "y"}},
    "limited": {"name": "⏳ Limited Offers", "params": {"sourceType": "561", "channel": "limitedoffers" , "afSmartRedirect": "y"}},
    "bigsave": {"name": "💰 Big Save", "params": {"sourceType": "680", "channel": "bigSave" , "afSmartRedirect": "y"}},
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

        detail_response = response_data.get('aliexpress_affiliate_productdetail_get_response')
        if not detail_response:
            logger.error(f"Missing 'aliexpress_affiliate_productdetail_get_response' key for ID {product_id}. Response: {response_data}")
            return None

        resp_result = detail_response.get('resp_result')
        if not resp_result:
             logger.error(f"Missing 'resp_result' key for ID {product_id}. Response: {detail_response}")
             return None

        resp_code = resp_result.get('resp_code')
        if resp_code != 200:
             resp_msg = resp_result.get('resp_msg', 'Unknown response message')
             logger.error(f"API response code not 200 for ID {product_id}. Code: {resp_code}, Msg: {resp_msg}")
             return None

        result = resp_result.get('result', {})
        products = result.get('products', {}).get('product', [])

        if not products:
            logger.warning(f"No products found in API response for ID {product_id}")
            return None

        product_data = products[0] 

        product_info = {
            'image_url': product_data.get('product_main_image_url'),
            'price': product_data.get('target_sale_price'),
            'currency': product_data.get('target_sale_price_currency', TARGET_CURRENCY),
            'title': product_data.get('product_title', f'Product {product_id}')
        }

        # Cache the result
        await product_cache.set(product_id, product_info)
        expiry_date = datetime.now() + timedelta(days=CACHE_EXPIRY_DAYS)
        logger.info(f"Cached product {product_id} until {expiry_date.strftime('%Y-%m-%d %H:%M:%S')}")

        return product_info

    except Exception as e:
        logger.exception(f"Error parsing product details response for ID {product_id}: {e}")
        return None

async def generate_affiliate_links_batch(target_urls: list[str]) -> dict[str, str | None]:
    """
    Generates affiliate links for a list of target URLs using a single API call for uncached URLs.
    Checks cache first, then fetches missing links in a batch.
    Returns a dictionary mapping each original target_url to its affiliate link (or None if failed).
    """
    results_dict = {}
    uncached_urls = []

    # 1. Check cache for each URL
    for url in target_urls:
        cached_link = await link_cache.get(url)
        if cached_link:
            logger.info(f"Cache hit for affiliate link: {url}")
            results_dict[url] = cached_link
        else:
            logger.debug(f"Cache miss for affiliate link: {url}")
            results_dict[url] = None # Initialize as None
            uncached_urls.append(url)

    # 2. If all URLs were cached, return immediately
    if not uncached_urls:
        logger.info("All affiliate links retrieved from cache.")
        return results_dict

    logger.info(f"Generating affiliate links for {len(uncached_urls)} uncached URLs: {', '.join(uncached_urls[:3])}...")

    # 3. Prepare and execute the batch API call
    # Check if URLs already have the star.aliexpress.com prefix before adding it
    prefixed_urls = []
    for url in uncached_urls:
        # Only add the prefix if it's not already there
        if "star.aliexpress.com/share/share.htm" not in url:
            prefixed_urls.append(f"https://star.aliexpress.com/share/share.htm?&redirectUrl={url}")
        else:
            prefixed_urls.append(url)
    source_values_str = ",".join(prefixed_urls)

    def _execute_batch_link_api():
        """Execute blocking batch API call in a thread pool."""
        try:
            request = iop.IopRequest('aliexpress.affiliate.link.generate')
            request.add_api_param('promotion_link_type', '0')
            request.add_api_param('source_values', source_values_str) # Comma-separated URLs
            request.add_api_param('tracking_id', ALIEXPRESS_TRACKING_ID)
            return aliexpress_client.execute(request)
        except Exception as e:
            logger.error(f"Error in batch link API call thread for URLs: {e}")
            return None

    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(executor, _execute_batch_link_api)

    # 4. Process the batch response
    if not response or not response.body:
        logger.error(f"Batch link generation API call failed or returned empty body for {len(uncached_urls)} URLs.")
        # Return the dictionary with cached values and Nones for failed ones
        return results_dict

    try:
        response_data = response.body
        if isinstance(response_data, str):
            try:
                response_data = json.loads(response_data)
            except json.JSONDecodeError as json_err:
                logger.error(f"Failed to decode JSON response for batch link generation: {json_err}. Response: {response_data[:500]}")
                return results_dict # Return partial results

        if 'error_response' in response_data:
            error_details = response_data.get('error_response', {})
            error_msg = error_details.get('msg', 'Unknown API error')
            error_code = error_details.get('code', 'N/A')
            logger.error(f"API Error for Batch Link Generation: Code={error_code}, Msg={error_msg}")
            return results_dict # Return partial results

        generate_response = response_data.get('aliexpress_affiliate_link_generate_response')
        if not generate_response:
            logger.error(f"Missing 'aliexpress_affiliate_link_generate_response' key in batch response. Response: {response_data}")
            return results_dict

        resp_result_outer = generate_response.get('resp_result')
        if not resp_result_outer:
            logger.error(f"Missing 'resp_result' key in batch response. Response: {generate_response}")
            return results_dict

        resp_code = resp_result_outer.get('resp_code')
        if resp_code != 200:
            resp_msg = resp_result_outer.get('resp_msg', 'Unknown response message')
            logger.error(f"API response code not 200 for batch link generation. Code: {resp_code}, Msg: {resp_msg}")
            return results_dict

        result = resp_result_outer.get('result', {})
        if not result:
            logger.error(f"Missing 'result' key in batch link response. Response: {resp_result_outer}")
            return results_dict

        links_data = result.get('promotion_links', {}).get('promotion_link', [])
        if not links_data or not isinstance(links_data, list):
            logger.warning(f"No 'promotion_links' found or not a list in batch response. Response: {result}")
            return results_dict # Return partial results

        # 5. Update results_dict and cache with fetched links
        expiry_date = datetime.now() + timedelta(days=CACHE_EXPIRY_DAYS)
        logger.info(f"Processing {len(links_data)} links from batch API response.")
        for link_info in links_data:
            if isinstance(link_info, dict):
                source_url = link_info.get('source_value')
                promo_link = link_info.get('promotion_link')

                if source_url and promo_link:
                    if source_url in results_dict: # Ensure we only update URLs we requested
                        results_dict[source_url] = promo_link
                        # Cache the result
                        await link_cache.set(source_url, promo_link)
                        logger.debug(f"Cached affiliate link for {source_url} until {expiry_date.strftime('%Y-%m-%d %H:%M:%S')}")
                    else:
                        logger.warning(f"Received link for unexpected source_value in batch response: {source_url}")
                else:
                    logger.warning(f"Missing 'source_value' or 'promotion_link' in batch response item: {link_info}")
            else:
                logger.warning(f"Promotion link data item is not a dictionary in batch response: {link_info}")

        # Log any URLs that were requested but not returned
        for url in uncached_urls:
            if results_dict.get(url) is None:
                logger.warning(f"No affiliate link returned or processed for requested URL: {url}")

        return results_dict

    except Exception as e:
        logger.exception(f"Error parsing batch link generation response: {e}")
        return results_dict # Return potentially partial results


# --- Telegram Command Handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a welcome message when the /start command is issued."""
    await update.message.reply_html(
        "Hello! Send me an AliExpress product link, and I'll try to generate affiliate links for it."
    )

# --- Telegram Message Processing ---

async def process_product_telegram(product_id: str, base_url: str, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fetches details, generates links, and sends a formatted message to Telegram."""
    chat_id = update.effective_chat.id
    logger.info(f"Processing Product ID: {product_id} for chat {chat_id}")

    try:
        # --- Fetch Product Details (API first, then Scrape Fallback) ---
        product_details = await fetch_product_details_v2(product_id)

        # Initialize variables
        product_image = None
        product_price = None
        product_currency = ''
        product_title = f"Product {product_id}" # Default title
        price_str = "Price not available"
        details_source = "None" # Track where details came from: 'API', 'Scraped', 'None'

        if product_details:
            # Details from API
            product_image = product_details.get('image_url')
            product_price = product_details.get('price')
            product_currency = product_details.get('currency', '')
            product_title = product_details.get('title', product_title) # Use API title or default
            price_str = f"{product_price} {product_currency}".strip() if product_price else price_str
            details_source = "API"
            logger.info(f"Successfully fetched details via API for product ID: {product_id}")
        else:
            # API failed, try scraping
            logger.warning(f"API failed for product ID: {product_id}. Attempting scraping fallback.")
            try:
                loop = asyncio.get_event_loop()
                # Run synchronous scraping function in executor
                scraped_name, scraped_image = await loop.run_in_executor(
                    executor, get_product_details_by_id, product_id
                )

                if scraped_name:
                    product_title = scraped_name # Use scraped title
                    product_image = scraped_image # Use scraped image (can be None)
                    details_source = "Scraped"
                    logger.info(f"Successfully scraped details for product ID: {product_id}")
                else:
                    logger.warning(f"Scraping also failed for product ID: {product_id}")
                    # Keep default title, image is None, price is unavailable
                    details_source = "None"

            except Exception as scrape_err:
                logger.error(f"Error during scraping fallback for product ID {product_id}: {scrape_err}")
                details_source = "None"

        # --- Generate Affiliate Links ---
        # 1. Build all target URLs for the different offers
        target_urls_map = {} # Map offer_key to target_url
        urls_to_fetch = []
        for offer_key in OFFER_ORDER:
            offer_info = OFFER_PARAMS[offer_key]
            params_for_offer = offer_info["params"]
            target_url = build_url_with_offer_params(base_url, params_for_offer)
            if target_url:
                target_urls_map[offer_key] = target_url
                urls_to_fetch.append(target_url)
            else:
                logger.warning(f"Could not build target URL for offer {offer_key} with base {base_url}")

        # 2. Generate affiliate links in a batch
        logger.info(f"Requesting batch affiliate links for product {product_id}")
        all_links_dict = await generate_affiliate_links_batch(urls_to_fetch) # Returns {target_url: promo_link | None}

        # 3. Map results back to offer keys
        generated_links = {} # Map offer_key to promo_link | None
        success_count = 0
        for offer_key, target_url in target_urls_map.items():
            promo_link = all_links_dict.get(target_url)
            generated_links[offer_key] = promo_link
            if promo_link:
                success_count += 1
            else:
                logger.warning(f"Failed to get affiliate link for offer {offer_key} (target: {target_url}) for product {product_id}")

        # --- Build the response message (HTML formatted) ---
        message_lines = []

        # Add title (always available, either API, scraped, or default)
        message_lines.append(f"<b>{product_title[:250]}</b>")

        # Add price only if available (from API)
        if details_source == "API" and product_price:
             message_lines.append(f"\n<b>Sale Price:</b> {price_str}\n")
        elif details_source == "Scraped":
             message_lines.append("\n<b>Sale Price:</b> Unavailable \n") 
        else: # details_source == "None"
             message_lines.append("\n<b>Product details unavailable</b>\n")

        message_lines.append("<b>Offers:</b>")

        for offer_key in OFFER_ORDER:
            link = generated_links.get(offer_key)
            offer_name = OFFER_PARAMS[offer_key]["name"]
            if link:
                # Ensure link is properly HTML escaped if needed (though URLs usually are safe)
                message_lines.append(f'{offer_name}: <a href="{link}">Click Here</a>')
            else:
                message_lines.append(f"{offer_name}: ❌ Failed")

        # Add footer text
        message_lines.append("\n<i>By RizoZ</i>")
        response_text = "\n".join(message_lines)

        # --- Create Inline Keyboard ---
        keyboard = [
            [
                InlineKeyboardButton("Choice Day", url="https://s.click.aliexpress.com/e/_oCPK1K1"),
                InlineKeyboardButton("Best Deals", url="https://s.click.aliexpress.com/e/_onx9vR3")
            ],
            [
                InlineKeyboardButton("GitHub", url="https://github.com/ReizoZ"),
                InlineKeyboardButton("Discord", url="https://discord.gg/9QzECYfmw8"),
                InlineKeyboardButton("Telegram", url="https://t.me/Aliexpress_Deal_Dz")
            ],
            [
                InlineKeyboardButton("☕ Buy Me Coffee", url="https://ko-fi.com/reizoz")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # --- Send the message ---
        response_text = "\n".join(message_lines) # Build the final text here

        if success_count > 0: # Check if any offer links were generated
            try:
                # Send photo only if an image URL exists (from API or scraping)
                if product_image:
                    await context.bot.send_photo(
                        chat_id=chat_id,
                        photo=product_image,
                        caption=response_text,
                        parse_mode=ParseMode.HTML,
                        reply_markup=reply_markup
                    )
                else:
                    # Send text message if no image available or if sending photo failed
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=response_text,
                        parse_mode=ParseMode.HTML,
                        disable_web_page_preview=True,
                        reply_markup=reply_markup
                    )
            except Exception as send_error:
                 logger.error(f"Failed to send message with keyboard for product {product_id} to chat {chat_id}: {send_error}")
                 # Fallback text message - send offers part if possible
                 offers_part = "\n".join(message_lines[message_lines.index("<b>Offers:</b>"):]) if "<b>Offers:</b>" in message_lines else "Offers unavailable."
                 await context.bot.send_message(
                     chat_id=chat_id,
                     text=f"⚠️ Error sending message for product {product_id}.\n\n{offers_part}",
                     parse_mode=ParseMode.HTML,
                     disable_web_page_preview=True,
                     reply_markup=reply_markup # Still try to send keyboard
                 )
        else:
            # No offer links generated
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"<b>{product_title[:250]}</b>\n\nWe couldn't find an offer for this product.", # Include title even if no offers
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
                reply_markup=reply_markup # Send keyboard even if no offers
            )

    except Exception as e:
        logger.exception(f"Unhandled error processing product {product_id} in chat {chat_id}: {e}")
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"An unexpected error occurred while processing product ID {product_id}. Sorry!"
            )
        except Exception:
            logger.error(f"Failed to send error message for product {product_id} to chat {chat_id}")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles incoming text messages, extracts URLs, and processes them."""
    if not update.message or not update.message.text:
        return
    message_text = update.message.text
    print(f"Received message: {message_text}")
    user = update.effective_user
    chat_id = update.effective_chat.id

    # Check if message is forwarded
    is_forwarded = update.message.forward_origin is not None
    if is_forwarded:
        origin_info = f" (originally from {update.message.forward_origin.sender_user.username})" if hasattr(update.message.forward_origin, 'sender_user') else ""
        logger.info(f"Processing forwarded message from {user.username or user.id} in chat {chat_id}{origin_info}")

    potential_urls = extract_potential_aliexpress_urls(message_text)
    if not potential_urls:
        # Send error message when no links are found
        await context.bot.send_message(
            chat_id=chat_id,
            text="❌ No AliExpress links found in your message. Please send a valid AliExpress product link."
        )
        return

    logger.info(f"Found {len(potential_urls)} potential URLs in message from {user.username or user.id} in chat {chat_id}")

    # Indicate processing
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    processed_product_ids = set()
    tasks = []
    async with aiohttp.ClientSession() as session:
        for url in potential_urls:
            original_url = url
            product_id = None
            base_url = None

            # Prepend https:// if missing and looks like an AE domain
            if not url.startswith(('http://', 'https://')):
                # Use a simple check for known AE domains before prepending
                if re.match(r'^(?:www\.|s\.click\.|a\.)?[\w-]*aliexpress\.(?:com|ru|es|fr|pt|it|pl|nl|co\.kr|co\.jp|com\.br|com\.tr|com\.vn|id|th|ar)', url, re.IGNORECASE):
                    logger.debug(f"Prepending https:// to potential URL: {url}")
                    url = f"https://{url}"
                else:
                    # If it doesn't start with http/https and doesn't look like an AE domain, skip it
                    logger.debug(f"Skipping potential URL without scheme or known AE domain: {original_url}")
                    continue

            # Check if it's a standard URL with an ID
            if STANDARD_ALIEXPRESS_DOMAIN_REGEX.match(url):
                product_id = extract_product_id(url)
                if product_id:
                    base_url = clean_aliexpress_url(url, product_id)
                    logger.debug(f"Found standard URL: {url} -> ID: {product_id}, Base: {base_url}")

            # Check if it's a known short link (s.click or a.aliexpress)
            elif SHORT_LINK_DOMAIN_REGEX.match(url):
                logger.debug(f"Found potential short link: {url}")
                final_url = await resolve_short_link(url, session)
                if final_url:
                    product_id = extract_product_id(final_url)
                    if product_id:
                        base_url = clean_aliexpress_url(final_url, product_id)
                        logger.debug(f"Resolved short link: {url} -> {final_url} -> ID: {product_id}, Base: {base_url}")
                else:
                     logger.warning(f"Could not resolve or extract ID from short link: {original_url} (resolved to: {final_url})")


            if product_id and base_url and product_id not in processed_product_ids:
                processed_product_ids.add(product_id)
                tasks.append(process_product_telegram(product_id, base_url, update, context))
            elif product_id and product_id in processed_product_ids:
                 logger.debug(f"Skipping duplicate product ID: {product_id}")


    if not tasks:
        logger.info(f"No processable AliExpress product links found after filtering/resolution in message from {user.username or user.id}")
        await context.bot.send_message(
            chat_id=chat_id,
            text="❌ We couldn't find any valid AliExpress product links in your message ❌"
        )
        return

    # If multiple links are being processed, notify the user
    if len(tasks) > 1:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"⏳ Processing {len(tasks)} AliExpress products from your message. Please wait..."
        )

    logger.info(f"Processing {len(tasks)} unique AliExpress products for chat {chat_id}")
    await asyncio.gather(*tasks)


# --- Main Bot Execution ---
def main() -> None:
    """Start the bot."""
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # --- Add Handlers ---
    # Command handlers
    application.add_handler(CommandHandler("start", start))

    # Message handler for text messages that are not commands
    # Using TEXT filter and checking for standard or known short link domains
    combined_domain_regex = re.compile(r'aliexpress\.com|s\.click\.aliexpress\.com|a\.aliexpress\.com', re.IGNORECASE)
    
    # Handle regular messages containing AliExpress links
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.Regex(combined_domain_regex),
        handle_message
    ))
    
    
    application.add_handler(MessageHandler(
        filters.FORWARDED  & filters.TEXT & filters.Regex(combined_domain_regex),  
        handle_message
    ))

    # Add a general message handler that responds to messages without links
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & ~filters.Regex(combined_domain_regex),
        lambda update, context: context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Please send an AliExpress product link to generate affiliate links."
        )
    ))

    # --- Setup Periodic Jobs ---
    job_queue = application.job_queue
    # Run cache cleanup once shortly after start, then every day
    job_queue.run_once(periodic_cache_cleanup, 60)
    job_queue.run_repeating(periodic_cache_cleanup, interval=timedelta(days=1), first=timedelta(days=1))

    # --- Start the Bot ---
    logger.info("Starting Telegram bot polling...")
    logger.info(f"Using AliExpress Key: {ALIEXPRESS_APP_KEY[:4]}...")
    logger.info(f"Using Tracking ID: {ALIEXPRESS_TRACKING_ID}")
    logger.info(f"Product Detail Settings: Currency={TARGET_CURRENCY}, Lang={TARGET_LANGUAGE}, Country={QUERY_COUNTRY}")
    logger.info(f"Query Fields: {QUERY_FIELDS}")
    logger.info(f"Cache expiry set to {CACHE_EXPIRY_DAYS} days")
    offer_names = [v['name'] for k, v in OFFER_PARAMS.items()]
    logger.info(f"Will generate links for offers: {', '.join(offer_names)}")
    logger.info("Bot is ready and listening for AliExpress links...")

    # Run the bot until the user presses Ctrl-C
    application.run_polling()

    # Clean shutdown for thread pool
    logger.info("Shutting down thread pool...")
    executor.shutdown(wait=True)
    logger.info("Bot stopped.")


if __name__ == "__main__":
    main()
