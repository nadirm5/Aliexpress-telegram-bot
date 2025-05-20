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

# Initialize caches
product_cache = CacheWithExpiry(CACHE_EXPIRY_SECONDS)
link_cache = CacheWithExpiry(CACHE_EXPIRY_SECONDS)
resolved_url_cache = CacheWithExpiry(CACHE_EXPIRY_SECONDS)

# --- Helper Functions ---

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
                    logger.info(f"Detected US domain in {final_url}, converting to .com domain")
                    final_url = final_url.replace('.aliexpress.us', '.aliexpress.com')
                    logger.info(f"Converted URL: {final_url}")
                
                if '_randl_shipto=' in final_url:
                    logger.info(f"Found _randl_shipto parameter in URL, replacing with QUERY_COUNTRY value")
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
        logger.exception(f"Unexpected error resolving short link {short_url}:
