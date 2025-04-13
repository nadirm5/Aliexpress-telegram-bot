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
# Updated to find aliexpress.com/..., s.click.aliexpress.com/... etc., even without http/www prefix
URL_REGEX = re.compile(r'https?://[^\s<>"]+|www\.[^\s<>"]+|\b(?:s\.click\.|a\.)?aliexpress\.(?:com|ru|es|fr|pt|it|pl|nl|co\.kr|co\.jp|com\.br|com\.tr|com\.vn|id|th|ar)(?:\.[\w-]+)?/[^\s<>"]*', re.IGNORECASE)
PRODUCT_ID_REGEX = re.compile(r'/item/(\d+)\.html')
# Matches standard AliExpress domains (requires https:// prepended if missing)
STANDARD_ALIEXPRESS_DOMAIN_REGEX = re.compile(r'https?://([\w-]+\.)?aliexpress\.(com|ru|es|fr|pt|it|pl|nl|co\.kr|co\.jp|com\.br|com\.tr|com\.vn|id\.aliexpress\.com|th\.aliexpress\.com|ar\.aliexpress\.com)(\.([\w-]+))?(/.*)?', re.IGNORECASE)
# Matches known short link domains (s.click.aliexpress.com and a.aliexpress.com)
# Using non-capturing group (?:...) and | for OR
SHORT_LINK_DOMAIN_REGEX = re.compile(r'https?://(?:s\.click\.aliexpress\.com/e/|a\.aliexpress\.com/_)[a-zA-Z0-9_-]+/?', re.IGNORECASE)


# --- Offer Parameter Mapping ---
OFFER_PARAMS = {
    "coin": {"name": "🪙 Coin", "params": {"sourceType": "620", "channel": "coin"}},
    "super": {"name": "🔥 Super Deals", "params": {"sourceType": "562","aff_fcid=": ""}},
    "limited": {"name": "⏳ Limited Offers", "params": {"sourceType": "561","aff_fcid=": ""}},
    "bigsave": {"name": "💰 Big Save", "params": {"sourceType": "680","aff_fcid=": ""}},
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
                if STANDARD_ALIEXPRESS_DOMAIN_REGEX.match(final_url) and extract_product_id(final_url):
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
    """Extracts the product ID from an AliExpress URL."""
    match = PRODUCT_ID_REGEX.search(url)
    return match.group(1) if match else None

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
        new_query_string = urlencode(params_to_add)
        # Reconstruct URL ensuring path is preserved correctly
        reconstructed_url = urlunparse((
            parsed_url.scheme,
            parsed_url.netloc,
            parsed_url.path,
            '',
            new_query_string,
            ''
        ))
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

async def generate_aliexpress_affiliate_link(target_url):
    """Generates an affiliate link using aliexpress.affiliate.link.generate with async cache."""
    cache_key = target_url
    cached_link = await link_cache.get(cache_key)
    if cached_link:
        logger.info(f"Cache hit for affiliate link: {target_url}")
        return cached_link

    logger.info(f"Generating affiliate link for: {target_url}")

    def _execute_link_api():
        """Execute blocking API call in a thread pool."""
        try:
            request = iop.IopRequest('aliexpress.affiliate.link.generate')
            request.add_api_param('promotion_link_type', '0')
            request.add_api_param('source_values', target_url)
            request.add_api_param('tracking_id', ALIEXPRESS_TRACKING_ID)

            return aliexpress_client.execute(request)
        except Exception as e:
            logger.error(f"Error in link API call thread for URL {target_url}: {e}")
            return None

    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(executor, _execute_link_api)

    if not response or not response.body:
        logger.error(f"Link generation API call failed or returned empty body for URL: {target_url}")
        return None

    try:
        response_data = response.body
        if isinstance(response_data, str):
             try:
                 response_data = json.loads(response_data)
             except json.JSONDecodeError as json_err:
                 logger.warning(f"Failed to decode JSON response for link generation ({target_url}): {json_err}. Attempting regex fallback.")
                 match = re.search(r'"promotion_link"\s*:\s*"([^"]+)"', response_data)
                 if match:
                     link = match.group(1).replace('\\/', '/')
                     logger.warning(f"Extracted link via regex fallback: {link}")
                     await link_cache.set(cache_key, link)
                     return link
                 else:
                    logger.error(f"JSON decode failed and regex fallback couldn't find link for {target_url}. Response: {response_data[:500]}")
                    return None


        if 'error_response' in response_data:
            error_details = response_data.get('error_response', {})
            error_msg = error_details.get('msg', 'Unknown API error')
            error_code = error_details.get('code', 'N/A')
            logger.error(f"API Error for Link Generation ({target_url}): Code={error_code}, Msg={error_msg}")
            return None

        generate_response = response_data.get('aliexpress_affiliate_link_generate_response')
        if not generate_response:
             logger.error(f"Missing 'aliexpress_affiliate_link_generate_response' key for URL {target_url}. Response: {response_data}")
             return None

        resp_result = generate_response.get('resp_result', {}).get('result', {})
        if not resp_result:
             logger.error(f"Missing 'resp_result' or 'result' key in link response for URL {target_url}. Response: {generate_response}")
             return None

        links_data = resp_result.get('promotion_links', {}).get('promotion_link', [])

        if not links_data or not isinstance(links_data, list) or len(links_data) == 0:
             logger.warning(f"No 'promotion_links' found or empty list for URL {target_url}. Response: {resp_result}")
             return None

        if isinstance(links_data[0], dict):
            link = links_data[0].get('promotion_link')
            if link:
                await link_cache.set(cache_key, link)
                expiry_date = datetime.now() + timedelta(days=CACHE_EXPIRY_DAYS)
                logger.info(f"Cached affiliate link for {target_url} until {expiry_date.strftime('%Y-%m-%d %H:%M:%S')}")
                return link
            else:
                 logger.warning(f"Found promotion link structure but 'promotion_link' key is missing or empty for URL {target_url}. Link data: {links_data[0]}")
                 return None
        else:
             logger.warning(f"Promotion link data is not a dictionary as expected for URL {target_url}. Data: {links_data[0]}")
             return None

    except Exception as e:
        logger.exception(f"Error parsing link generation response for URL {target_url}: {e}")
        return None


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
        # Fetch product details
        product_details = await fetch_product_details_v2(product_id)

        if not product_details:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"❌ Could not fetch details for product ID: {product_id}"
            )
            return

        product_image = product_details.get('image_url')
        product_price = product_details.get('price')
        product_currency = product_details.get('currency', '')
        product_title = product_details.get('title', f"Product {product_id}")

        # Format price string
        price_str = f"{product_price} {product_currency}".strip() if product_price else "Price not available"

        # Generate affiliate links concurrently
        link_tasks = []
        for offer_key in OFFER_ORDER:
            offer_info = OFFER_PARAMS[offer_key]
            params_for_offer = offer_info["params"]
            target_url = build_url_with_offer_params(base_url, params_for_offer)
            target_url=f"https://star.aliexpress.com/share/share.htm?platform=AE&businessType=ProductDetail&redirectUrl={target_url}"
            task = generate_aliexpress_affiliate_link(target_url)
            link_tasks.append((offer_key, task))

        # Await all link generation tasks
        generated_links = {}
        results = await asyncio.gather(*(task for _, task in link_tasks), return_exceptions=True)

        success_count = 0
        for i, (offer_key, _) in enumerate(link_tasks):
             result = results[i]
             if isinstance(result, Exception):
                 logger.error(f"Error generating link for {offer_key} ({product_id}): {result}")
                 generated_links[offer_key] = None
             elif result:
                 generated_links[offer_key] = result
                 success_count += 1
             else:
                 generated_links[offer_key] = None

        # Build the response message (HTML formatted)
        message_lines = [
            f"<b>{product_title[:250]}</b>",
            f"\n<b>Sale Price:</b> {price_str}\n",
            "<b>Offers:</b>"
        ]

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

        # Send the message (photo with caption if image available, else text)
        if success_count > 0:
            try:
                if product_image:
                    await context.bot.send_photo(
                        chat_id=chat_id,
                        photo=product_image,
                        caption=response_text,
                        parse_mode=ParseMode.HTML,
                        reply_markup=reply_markup
                    )
                else:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=response_text,
                        parse_mode=ParseMode.HTML,
                        disable_web_page_preview=True,
                        reply_markup=reply_markup
                    )
            except Exception as send_error:
                 logger.error(f"Failed to send message with keyboard for product {product_id} to chat {chat_id}: {send_error}")
                 await context.bot.send_message(
                     chat_id=chat_id,
                     text=f"⚠️ Error formatting or sending message for product {product_id}. Please check logs."
                 )
        else:
            await context.bot.send_message(
                chat_id=chat_id,
                text="We couldn't find an offer for this product"
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


            # If we got a valid product ID and base URL, and haven't processed this ID yet
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
