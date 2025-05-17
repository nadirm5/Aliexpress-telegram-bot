import logging
import os
import re
import json
import asyncio
import time
from datetime import datetime, timedelta
from urllib.parse import urlparse, urlunparse, urlencode
from concurrent.futures import ThreadPoolExecutor
import aiohttp
from dotenv import load_dotenv

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, JobQueue
from telegram.constants import ParseMode, ChatAction

import iop
from aliexpress_utils import get_product_details_by_id

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
ALIEXPRESS_APP_KEY = os.getenv('ALIEXPRESS_APP_KEY')
ALIEXPRESS_APP_SECRET = os.getenv('ALIEXPRESS_APP_SECRET')
TARGET_CURRENCY = os.getenv('TARGET_CURRENCY', 'USD')
TARGET_LANGUAGE = os.getenv('TARGET_LANGUAGE', 'en')
QUERY_COUNTRY = os.getenv('QUERY_COUNTRY', 'US')
ALIEXPRESS_TRACKING_ID = os.getenv('ALIEXPRESS_TRACKING_ID', 'default')
ALIEXPRESS_API_URL = 'https://api-sg.aliexpress.com/sync'
QUERY_FIELDS = 'product_main_image_url,target_sale_price,product_title,target_sale_price_currency'
CACHE_EXPIRY_DAYS = 1
CACHE_EXPIRY_SECONDS = CACHE_EXPIRY_DAYS * 24 * 60 * 60
MAX_WORKERS = 10

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

if not all([TELEGRAM_BOT_TOKEN, ALIEXPRESS_APP_KEY, ALIEXPRESS_APP_SECRET, ALIEXPRESS_TRACKING_ID]):
    logger.error("Error: Missing required environment variables.")
    exit()

try:
    aliexpress_client = iop.IopClient(ALIEXPRESS_API_URL, ALIEXPRESS_APP_KEY, ALIEXPRESS_APP_SECRET)
    logger.info("AliExpress API client initialized.")
except Exception as e:
    logger.exception(f"Error initializing AliExpress API client: {e}")
    exit()



executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)

URL_REGEX = re.compile(r'https?://[^\s<>"]+|www\.[^\s<>"]+|\b(?:s\.click\.|a\.)?aliexpress\.(?:com|ru|es|fr|pt|it|pl|nl|co\.kr|co\.jp|com\.br|com\.tr|com\.vn|us|id|th|ar)(?:\.[\w-]+)?/[^\s<>"]*', re.IGNORECASE)
PRODUCT_ID_REGEX = re.compile(r'/item/(\d+)\.html')
STANDARD_ALIEXPRESS_DOMAIN_REGEX = re.compile(r'https?://(?!a\.|s\.click\.)([\w-]+\.)?aliexpress\.(com|ru|es|fr|pt|it|pl|nl|co\.kr|co\.jp|com\.br|com\.tr|com\.vn|us|id\.aliexpress\.com|th\.aliexpress\.com|ar\.aliexpress\.com)(\.([\w-]+))?(/.*)?', re.IGNORECASE)
SHORT_LINK_DOMAIN_REGEX = re.compile(r'https?://(?:s\.click\.aliexpress\.com/e/|a\.aliexpress\.com/_)[a-zA-Z0-9_-]+/?', re.IGNORECASE)
COMBINED_DOMAIN_REGEX = re.compile(r'aliexpress\.com|s\.click\.aliexpress\.com|a\.aliexpress\.com', re.IGNORECASE)

OFFER_PARAMS = {
    "coin": {
        "name": "🪙 <b>🎯 Coins</b> – <b>الرابط بالتخفيض ⬇️ أقل سعر بالعملات 💸</b> 👉",
        "params": {
            "sourceType": "620%26channel=coin",
            "afSmartRedirect": "y"
        }
    },

    "link": {
        "name": "🚀 <b>🔗 رابط المنتوج بالتخفيض</b>",
        "params": {
            "sourceType": "620%26channel=coin",
            "afSmartRedirect": "y"
    
        }
    },


    
    "super": {"name": "🔥 Super Deals", "params": {"sourceType": "562", "channel": "sd", "afSmartRedirect": "y"}},
    "limited": {"name": "⏳ Limited Offers", "params": {"sourceType": "561", "channel": "limitedoffers", "afSmartRedirect": "y"}},
    "bigsave": {"name": "💰 Big Save", "params": {"sourceType": "680", "channel": "bigSave", "afSmartRedirect": "y"}},
}

OFFER_ORDER = ["coin", "super", "limited", "bigsave"]

class CacheWithExpiry:
    def __init__(self, expiry_seconds):
        self.cache = {}
        self.expiry_seconds = expiry_seconds
        self._lock = asyncio.Lock()

    async def get(self, key):
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
        async with self._lock:
            self.cache[key] = (value, time.time())
            logger.debug(f"Cached value for key: {key}")

    async def clear_expired(self):
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

product_cache = CacheWithExpiry(CACHE_EXPIRY_SECONDS)
link_cache = CacheWithExpiry(CACHE_EXPIRY_SECONDS)
resolved_url_cache = CacheWithExpiry(CACHE_EXPIRY_SECONDS)

async def resolve_short_link(short_url: str, session: aiohttp.ClientSession) -> str | None:
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
                    final_url = final_url.replace('.aliexpress.us', '.aliexpress.com')
                    logger.info(f"Converted US domain URL: {final_url}")

                if '_randl_shipto=' in final_url:
                    final_url = re.sub(r'_randl_shipto=[^&]+', f'_randl_shipto={QUERY_COUNTRY}', final_url)
                    logger.info(f"Updated URL with correct country: {final_url}")
                    try:
                        logger.info(f"Re-fetching URL with updated country parameter: {final_url}")
                        async with session.get(final_url, allow_redirects=True, timeout=10) as country_response:
                            if country_response.status == 200 and country_response.url:
                                final_url = str(country_response.url)
                                logger.info(f"Re-fetched URL with correct country: {final_url}")
                    except Exception as e:
                        logger.warning(f"Error re-fetching URL with updated country parameter: {e}")

                product_id = extract_product_id(final_url)
                if STANDARD_ALIEXPRESS_DOMAIN_REGEX.match(final_url) and product_id:
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

def extract_product_id(url: str) -> str | None:
    if '.aliexpress.us' in url:
        url = url.replace('.aliexpress.us', '.aliexpress.com')

    match = PRODUCT_ID_REGEX.search(url)
    if match:
        return match.group(1)

    alt_patterns = [r'/p/[^/]+/([0-9]+)\.html', r'product/([0-9]+)']
    for pattern in alt_patterns:
        alt_match = re.search(pattern, url)
        if alt_match:
            product_id = alt_match.group(1)
            logger.info(f"Extracted product ID {product_id} using alternative pattern {pattern}")
            return product_id

    logger.warning(f"Could not extract product ID from URL: {url}")
    return None

def extract_potential_aliexpress_urls(text: str) -> list[str]:
    return URL_REGEX.findall(text)

def clean_aliexpress_url(url: str, product_id: str) -> str | None:
    try:
        parsed_url = urlparse(url)
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

def build_url_with_offer_params(base_url: str, params_to_add: dict) -> str | None:
    if not params_to_add:
        return base_url

    try:
        parsed_url = urlparse(base_url)
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
        return f"https://star.aliexpress.com/share/share.htm?platform=AE&businessType=ProductDetail&redirectUrl={reconstructed_url}"
    except ValueError:
        logger.error(f"Error building URL with params for base: {base_url}")
        return base_url # Return original on error? Or None? Returning base for now.

async def periodic_cache_cleanup(context: ContextTypes.DEFAULT_TYPE):
    try:
        product_expired = await product_cache.clear_expired()
        link_expired = await link_cache.clear_expired()
        resolved_expired = await resolved_url_cache.clear_expired()
        logger.info(f"Cache cleanup: Removed {product_expired} product, {link_expired} link, {resolved_expired} resolved URL items.")
        logger.info(f"Cache stats: {len(product_cache.cache)} products, {len(link_cache.cache)} links, {len(resolved_url_cache.cache)} resolved URLs in cache.")
    except Exception as e:
        logger.error(f"Error in periodic cache cleanup job: {e}")

async def fetch_product_details_v2(product_id: str) -> dict | None:
    cached_data = await product_cache.get(product_id)
    if cached_data:
        logger.info(f"Cache hit for product ID: {product_id}")
        return cached_data

    logger.info(f"Fetching product details for ID: {product_id}")

    def _execute_api_call():
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
        if isinstance(response_data, str):
            try:
                response_data = json.loads(response_data)
            except json.JSONDecodeError as json_err:
                logger.error(f"Failed to decode JSON response for product {product_id}: {json_err}. Response: {response_data[:500]}")
                return None

        if 'error_response' in response_data:
            error_details = response_data.get('error_response', {})
            logger.error(f"API Error for Product ID {product_id}: Code={error_details.get('code', 'N/A')}, Msg={error_details.get('msg', 'Unknown API error')}")
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
             logger.error(f"API response code not 200 for ID {product_id}. Code: {resp_code}, Msg: {resp_result.get('resp_msg', 'Unknown')}")
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

        await product_cache.set(product_id, product_info)
        expiry_date = datetime.now() + timedelta(days=CACHE_EXPIRY_DAYS)
        logger.info(f"Cached product {product_id} until {expiry_date.strftime('%Y-%m-%d %H:%M:%S')}")
        return product_info

    except Exception as e:
        logger.exception(f"Error parsing product details response for ID {product_id}: {e}")
        return None

async def generate_affiliate_links_batch(target_urls: list[str]) -> dict[str, str | None]:
    results_dict = {}
    uncached_urls = []

    for url in target_urls:
        cached_link = await link_cache.get(url)
        if cached_link:
            logger.info(f"Cache hit for affiliate link: {url}")
            results_dict[url] = cached_link
        else:
            logger.debug(f"Cache miss for affiliate link: {url}")
            results_dict[url] = None
            uncached_urls.append(url)

    if not uncached_urls:
        logger.info("All affiliate links retrieved from cache.")
        return results_dict

    logger.info(f"Generating affiliate links for {len(uncached_urls)} uncached URLs...")

    prefixed_urls = []
    for url in uncached_urls:
        if "star.aliexpress.com/share/share.htm" not in url:
            prefixed_urls.append(f"https://star.aliexpress.com/share/share.htm?platform=AE&businessType=ProductDetail&redirectUrl={url}")
        else:
            prefixed_urls.append(url)
    source_values_str = ",".join(prefixed_urls)

    def _execute_batch_link_api():
        try:
            request = iop.IopRequest('aliexpress.affiliate.link.generate')
            request.add_api_param('promotion_link_type', '0')
            request.add_api_param('source_values', source_values_str)
            request.add_api_param('tracking_id', ALIEXPRESS_TRACKING_ID)
            return aliexpress_client.execute(request)
        except Exception as e:
            logger.error(f"Error in batch link API call thread for URLs: {e}")
            return None

    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(executor, _execute_batch_link_api)

    if not response or not response.body:
        logger.error(f"Batch link generation API call failed or returned empty body for {len(uncached_urls)} URLs.")
        return results_dict

    try:
        response_data = response.body
        if isinstance(response_data, str):
            try:
                response_data = json.loads(response_data)
            except json.JSONDecodeError as json_err:
                logger.error(f"Failed to decode JSON response for batch link generation: {json_err}. Response: {response_data[:500]}")
                return results_dict

        if 'error_response' in response_data:
            error_details = response_data.get('error_response', {})
            logger.error(f"API Error for Batch Link Generation: Code={error_details.get('code', 'N/A')}, Msg={error_details.get('msg', 'Unknown')}")
            return results_dict

        generate_response = response_data.get('aliexpress_affiliate_link_generate_response')
        if not generate_response:
            logger.error(f"Missing 'aliexpress_affiliate_link_generate_response' key. Response: {response_data}")
            return results_dict

        resp_result_outer = generate_response.get('resp_result')
        if not resp_result_outer:
            logger.error(f"Missing 'resp_result' key. Response: {generate_response}")
            return results_dict

        resp_code = resp_result_outer.get('resp_code')
        if resp_code != 200:
            logger.error(f"API response code not 200 for batch link generation. Code: {resp_code}, Msg: {resp_result_outer.get('resp_msg', 'Unknown')}")
            return results_dict

        result = resp_result_outer.get('result', {})
        if not result:
            logger.error(f"Missing 'result' key. Response: {resp_result_outer}")
            return results_dict

        links_data = result.get('promotion_links', {}).get('promotion_link', [])
        if not links_data or not isinstance(links_data, list):
            logger.warning(f"No 'promotion_links' found or not a list. Response: {result}")
            return results_dict

        expiry_date = datetime.now() + timedelta(days=CACHE_EXPIRY_DAYS)
        logger.info(f"Processing {len(links_data)} links from batch API response.")
        for link_info in links_data:
            if isinstance(link_info, dict):
                source_url = link_info.get('source_value')
                promo_link = link_info.get('promotion_link')

                if source_url and promo_link:
                    # Find the original uncached URL that corresponds to this source_value
                    # This assumes the API returns source_value exactly as sent
                    original_target_url = None
                    for target in uncached_urls:
                        # Check if the source_url (which has the star prefix) contains the original target url
                        if f"redirectUrl={target}" in source_url or target == source_url:
                             original_target_url = target
                             break
                        # Fallback check if the source_url itself matches an original target (less likely)
                        elif source_url == target:
                             original_target_url = target
                             break

                    if original_target_url and original_target_url in results_dict:
                        results_dict[original_target_url] = promo_link
                        await link_cache.set(original_target_url, promo_link)
                        logger.debug(f"Cached aff
