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
    "bundle": {
        "name": "📦 <b>Bundle Deals</b> – <b>أفضل تخفيض من عروض البندل</b> 🔗",
        "params": {
            "sourceType": "690",
            "channel": "bundle",
            "afSmartRedirect": "y"
        }
    }
}

OFFER_ORDER = ["coin", "bundle"]

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

        if not parsed_url.path or product_id not in parsed_url.path:
            logger.warning(f"URL path does not contain product ID: {url}")
            return None

        new_url = urlunparse((
            parsed_url.scheme,
            parsed_url.netloc,
            path_segment,
            '', '', ''
        ))

        logger.debug(f"Cleaned AliExpress URL: {new_url}")
        return new_url
    except Exception as e:
        logger.error(f"Error cleaning AliExpress URL {url}: {e}")
        return None

def build_url_with_offer_params(base_url: str, offer_params: dict) -> str | None:
    try:
        parsed_url = urlparse(base_url)
        query = dict(re.findall(r'([^&=?]+)=([^&]+)', parsed_url.query))
        query.update(offer_params)
        query['aff_fcid'] = ALIEXPRESS_TRACKING_ID
        query['aff_platform'] = 'portals-tool'
        query['sk'] = ''
        query['aff_trace_key'] = ''
        query['terminal_id'] = ''
        query['dp'] = 'false'

        query_string = urlencode(query)
        full_url = urlunparse((
            parsed_url.scheme,
            parsed_url.netloc,
            parsed_url.path,
            parsed_url.params,
            query_string,
            parsed_url.fragment
        ))
        return full_url
    except Exception as e:
        logger.error(f"Error building offer URL from base {base_url} with params {offer_params}: {e}")
        return None

def generate_offer_links(original_url: str) -> list[str]:
    product_id = extract_product_id(original_url)
    if not product_id:
        return []

    clean_url = clean_aliexpress_url(original_url, product_id)
    if not clean_url:
        return []

    result_links = []
    for offer_key in OFFER_ORDER:
        offer = OFFER_PARAMS[offer_key]
        offer_url = build_url_with_offer_params(clean_url, offer["params"])
        if offer_url:
            result_links.append(f"{offer['name']}\n{offer_url}")

    return result_links

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    urls = extract_potential_aliexpress_urls(text)
    if not urls:
        return

    # Pour simplifier, on prend le premier lien trouvé
    original_url = urls[0]

    # Si c'est un lien court, on résout l'URL complète
    if SHORT_LINK_DOMAIN_REGEX.match(original_url):
        async with aiohttp.ClientSession() as session:
            resolved_url = await resolve_short_link(original_url, session)
            if resolved_url:
                original_url = resolved_url
            else:
                await update.message.reply_text("Impossible de résoudre le lien court AliExpress.")
                return

    offer_links = generate_offer_links(original_url)
    if not offer_links:
        await update.message.reply_text("Lien AliExpress non valide ou produit introuvable.")
        return

    response_text = "\n\n".join(offer_links)
    await update.message.reply_text(response_text, parse_mode=ParseMode.HTML)

def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot démarré.")
    app.run_polling()

if __name__ == '__main__':
    main()
