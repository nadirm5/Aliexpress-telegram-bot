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
TARGET_CURRENCY = os.getenv('TARGET_CURRENCY', 'USD') # Default if not set
TARGET_LANGUAGE = os.getenv('TARGET_LANGUAGE', 'en') # Default if not set
QUERY_COUNTRY = os.getenv('QUERY_COUNTRY', 'US')     # Default if not set
ALIEXPRESS_TRACKING_ID = os.getenv('ALIEXPRESS_TRACKING_ID', 'default')

# --- Basic Logging Setup ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- AliExpress API Configuration ---
ALIEXPRESS_API_URL = 'https://api-sg.aliexpress.com/sync'
QUERY_FIELDS = 'product_main_image_url,target_sale_price,product_title,target_sale_price_currency'

# Thread pool for blocking API calls
executor = ThreadPoolExecutor(max_workers=10)

# --- Cache Configuration ---
CACHE_EXPIRY_DAYS = 7
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
URL_REGEX = re.compile(r'https?://[^\s<>"]+|www\.[^\s<>"]+')
PRODUCT_ID_REGEX = re.compile(r'/item/(\d+)\.html')
ALIEXPRESS_DOMAIN_REGEX = re.compile(r'https?://([\w-]+\.)?aliexpress\.(com|ru|es|fr|pt|it|pl|nl|co\.kr|co\.jp|com\.br|com\.tr|com\.vn|id\.aliexpress\.com|th\.aliexpress\.com|ar\.aliexpress\.com)(\.([\w-]+))?(/.*)?', re.IGNORECASE)

# --- Offer Parameter Mapping ---
OFFER_PARAMS = {
    "coin": {"name": "🪙 Coin", "params": {"sourceType": "620", "channel": "coin"}},
    "super": {"name": "🔥 Super Deals", "params": {"sourceType": "562"}},
    "limited": {"name": "⏳ Limited Offers", "params": {"sourceType": "561"}},
    "bigsave": {"name": "💰 Big Save", "params": {"sourceType": "680"}},
}
OFFER_ORDER = ["coin", "super", "limited", "bigsave"]

# --- Cache Implementation with Expiry ---
class CacheWithExpiry:
    def __init__(self, expiry_seconds):
        self.cache = {}
        self.expiry_seconds = expiry_seconds
        self._lock = asyncio.Lock() # Lock for async access

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
                    pass # Already deleted, potentially by another task
            return count

# Initialize caches
product_cache = CacheWithExpiry(CACHE_EXPIRY_SECONDS)
link_cache = CacheWithExpiry(CACHE_EXPIRY_SECONDS)

# --- Helper Functions (Mostly Unchanged) ---

def extract_product_id(url):
    """Extracts the product ID from an AliExpress URL."""
    match = PRODUCT_ID_REGEX.search(url)
    return match.group(1) if match else None

def extract_valid_aliexpress_urls_with_ids(text):
    """Finds unique AliExpress URLs containing product IDs - Optimized version."""
    potential_urls = URL_REGEX.findall(text)
    valid_urls = {}  # Use dict {product_id: base_url}

    for url in potential_urls:
        # Basic sanity check for length and common TLDs before heavier regex
        if len(url) > 20 and '.aliexpress.' in url:
            if ALIEXPRESS_DOMAIN_REGEX.match(url):
                product_id = extract_product_id(url)
                if product_id and product_id not in valid_urls:
                    try:
                        parsed_url = urlparse(url)
                        # Reconstruct a cleaner base URL
                        base_url = urlunparse((
                            parsed_url.scheme or 'https', # Ensure scheme
                            parsed_url.netloc,
                            parsed_url.path,
                            '', '', '' # Remove params, query, fragment
                         ))
                        # Ensure path ends correctly
                        if product_id and f'/item/{product_id}.html' not in base_url:
                             # If ID was found but path doesn't match, reconstruct carefully
                             path_segment = f'/item/{product_id}.html'
                             base_url = urlunparse((
                                parsed_url.scheme or 'https',
                                parsed_url.netloc,
                                path_segment,
                                '', '', ''
                             ))

                        valid_urls[product_id] = base_url
                    except ValueError:
                        logger.warning(f"Could not parse potentially malformed URL: {url}")
                        continue # Skip malformed URLs

    return list(valid_urls.items())


def build_url_with_offer_params(base_url, params_to_add):
    """Adds offer parameters to a base URL."""
    if not params_to_add:
        return base_url

    try:
        parsed_url = urlparse(base_url)
        # Important: Create a *new* query string, don't modify existing 'params' attribute
        new_query_string = urlencode(params_to_add)
        # Reconstruct URL ensuring path is preserved correctly
        # Using path, not params, for query string placement
        reconstructed_url = urlunparse((
            parsed_url.scheme,
            parsed_url.netloc,
            parsed_url.path,
            '', # No path parameters
            new_query_string, # Query string
            '' # No fragment
        ))
        return reconstructed_url
    except ValueError:
        logger.error(f"Error building URL with params for base: {base_url}")
        return base_url # Return original on error


# --- Maintenance Task ---
async def periodic_cache_cleanup(context: ContextTypes.DEFAULT_TYPE):
    """Periodically clean up expired cache items (Job Queue callback)"""
    try:
        product_expired = await product_cache.clear_expired()
        link_expired = await link_cache.clear_expired()
        logger.info(f"Cache cleanup: Removed {product_expired} product items, {link_expired} link items.")
        logger.info(f"Cache stats: {len(product_cache.cache)} products, {len(link_cache.cache)} links in cache.")
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
    cache_key = target_url # Use the full target URL as the key
    cached_link = await link_cache.get(cache_key)
    if cached_link:
        logger.info(f"Cache hit for affiliate link: {target_url}")
        return cached_link

    logger.info(f"Generating affiliate link for: {target_url}")

    def _execute_link_api():
        """Execute blocking API call in a thread pool."""
        try:
            request = iop.IopRequest('aliexpress.affiliate.link.generate')
            request.add_api_param('promotion_link_type', '0') # 0 for specific links
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
                 # Attempt regex extraction as a fallback for potentially malformed JSON
                 # This is fragile and should ideally not be needed if the API/SDK is reliable
                 logger.warning(f"Failed to decode JSON response for link generation ({target_url}): {json_err}. Attempting regex fallback.")
                 match = re.search(r'"promotion_link"\s*:\s*"([^"]+)"', response_data)
                 if match:
                     link = match.group(1).replace('\\/', '/') # Fix escaped slashes
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
             # Check if maybe the structure is different? Log the generate_response
             logger.error(f"Missing 'resp_result' or 'result' key in link response for URL {target_url}. Response: {generate_response}")
             return None

        links_data = resp_result.get('promotion_links', {}).get('promotion_link', [])

        if not links_data or not isinstance(links_data, list) or len(links_data) == 0:
             logger.warning(f"No 'promotion_links' found or empty list for URL {target_url}. Response: {resp_result}")
             return None

        # Assuming the first link is the one we want
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
            # Add task to list
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
                 generated_links[offer_key] = None # Explicitly None if generation returned None/empty

        # Build the response message (HTML formatted)
        # Use HTML for better link handling and formatting robustness
        message_lines = [
            f"<b>{product_title[:250]}</b>", # Limit title length
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

        # Add static links and footer
        message_lines.extend([
            "\n", # Spacer
             '<a href="https://s.click.aliexpress.com/e/_oCPK1K1">Choice Day</a> | <a href="https://s.click.aliexpress.com/e/_onx9vR3">Best Deals</a>',
            "\n", # Spacer
             '<a href="https://github.com/ReizoZ">GitHub</a> | <a href="https://discord.gg/9QzECYfmw8">Discord</a> | <a href="https://t.me/Aliexpress_Deal_Dz">Telegram</a>',
             "\n<i>By RizoZ</i>"
        ])

        response_text = "\n".join(message_lines)

        # Send the message (photo with caption if image available, else text)
        if success_count > 0:
            try:
                if product_image:
                    await context.bot.send_photo(
                        chat_id=chat_id,
                        photo=product_image,
                        caption=response_text,
                        parse_mode=ParseMode.HTML
                    )
                else:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=response_text,
                        parse_mode=ParseMode.HTML,
                        disable_web_page_preview=True # Often better for these messages
                    )
            except Exception as send_error: # Catch potential Telegram API errors during send
                 logger.error(f"Failed to send message for product {product_id} to chat {chat_id}: {send_error}")
                 # Maybe send a fallback plain text error?
                 await context.bot.send_message(
                     chat_id=chat_id,
                     text=f"⚠️ Error formatting or sending message for product {product_id}. Please check logs."
                 )
        else:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"❌ Could not generate any affiliate links for Product ID {product_id}"
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
        return # Ignore messages without text

    message_text = update.message.text
    user = update.effective_user
    chat_id = update.effective_chat.id

    # Extract potential AliExpress URLs with Product IDs
    urls_to_process = extract_valid_aliexpress_urls_with_ids(message_text)

    if not urls_to_process:
        # If the message contained 'aliexpress.com' but no valid product ID URL, maybe ignore or reply?
        # For now, just ignore if no processable URLs found.
        # logger.debug(f"No valid AliExpress product URLs found in message from {user.username or user.id} in chat {chat_id}")
        return

    logger.info(f"Found {len(urls_to_process)} AliExpress URLs in message from {user.username or user.id} in chat {chat_id}")

    # Indicate processing
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    # Create and run processing tasks concurrently
    tasks = [
        process_product_telegram(product_id, base_url, update, context)
        for product_id, base_url in urls_to_process
    ]
    await asyncio.gather(*tasks)


# --- Main Bot Execution ---
def main() -> None:
    """Start the bot."""
    # Create the Application and pass it your bot's token.
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # --- Add Handlers ---
    # Command handlers
    application.add_handler(CommandHandler("start", start))

    # Message handler for text messages that are not commands
    # Using TEXT filter and ensuring it finds 'aliexpress.' for basic pre-filtering
    # The main logic is inside handle_message
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.Regex(ALIEXPRESS_DOMAIN_REGEX),
        handle_message
    ))
    # You might want a separate handler or adjust the above if you need to catch
    # messages *without* aliexpress links too for other purposes.

    # --- Setup Periodic Jobs ---
    job_queue = application.job_queue
    # Run cache cleanup once shortly after start, then every day
    job_queue.run_once(periodic_cache_cleanup, 60) # Run 1 min after start
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

    # Clean shutdown for thread pool (optional but good practice)
    logger.info("Shutting down thread pool...")
    executor.shutdown(wait=True)
    logger.info("Bot stopped.")


if __name__ == "__main__":
    main()