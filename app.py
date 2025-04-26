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
    "coin": {"name": "🪙 Coin", "params": {"sourceType": "620%26channel=coin"}},
    "super": {"name": "🔥 Super Deals", "params": {"sourceType": "562", "channel": "sd"}},
    "limited": {"name": "⏳ Limited Offers", "params": {"sourceType": "561", "channel": "limitedoffers"}},
    "bigsave": {"name": "💰 Big Save", "params": {"sourceType": "680", "channel": "bigSave"}},
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
                netloc = f"www.aliexpress.{parts[-1]}"

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
                        logger.debug(f"Cached affiliate link for {original_target_url} until {expiry_date.strftime('%Y-%m-%d %H:%M:%S')}")
                    else:
                        logger.warning(f"Received link for unexpected or unmatchable source_value: {source_url}")
                else:
                    logger.warning(f"Missing 'source_value' or 'promotion_link' in batch response item: {link_info}")
            else:
                logger.warning(f"Promotion link data item is not a dictionary: {link_info}")

        for url in uncached_urls:
            if results_dict.get(url) is None:
                logger.warning(f"No affiliate link returned or processed for requested URL: {url}")

        return results_dict

    except Exception as e:
        logger.exception(f"Error parsing batch link generation response: {e}")
        return results_dict

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_html(
        "👋 Welcome to the AliExpress Discount Bot! 🛍️\n\n"
        "🔍 <b>How to use:</b>\n"
        "1️⃣ Copy an AliExpress product link 📋\n"
        "2️⃣ Send the link here 📤\n"
        "3️⃣ Get affiliate links back ✨\n\n"
        "🔗 Supports regular & short links.\n"
        "🚀 Send a link to start! 🎁"
    )

async def _get_product_data(product_id: str) -> tuple[dict | None, str]:
    product_details = await fetch_product_details_v2(product_id)
    details_source = "None"

    if product_details:
        details_source = "API"
        logger.info(f"Successfully fetched details via API for product ID: {product_id}")
        return product_details, details_source
    else:
        logger.warning(f"API failed for product ID: {product_id}. Attempting scraping fallback.")
        try:
            loop = asyncio.get_event_loop()
            scraped_name, scraped_image = await loop.run_in_executor(
                executor, get_product_details_by_id, product_id
            )
            if scraped_name:
                details_source = "Scraped"
                logger.info(f"Successfully scraped details for product ID: {product_id}")
                return {'title': scraped_name, 'image_url': scraped_image, 'price': None, 'currency': None}, details_source
            else:
                logger.warning(f"Scraping also failed for product ID: {product_id}")
                return {'title': f"Product {product_id}", 'image_url': None, 'price': None, 'currency': None}, details_source
        except Exception as scrape_err:
            logger.error(f"Error during scraping fallback for product ID {product_id}: {scrape_err}")
            return {'title': f"Product {product_id}", 'image_url': None, 'price': None, 'currency': None}, details_source

async def _generate_offer_links(base_url: str) -> dict[str, str | None]:
    target_urls_map = {}
    urls_to_fetch = []
    for offer_key in OFFER_ORDER:
        offer_info = OFFER_PARAMS[offer_key]
        target_url = build_url_with_offer_params(base_url, offer_info["params"])
        if target_url:
            target_urls_map[offer_key] = target_url
            urls_to_fetch.append(target_url)
        else:
            logger.warning(f"Could not build target URL for offer {offer_key} with base {base_url}")

    if not urls_to_fetch:
        return {}

    all_links_dict = await generate_affiliate_links_batch(urls_to_fetch)

    generated_links = {}
    for offer_key, target_url in target_urls_map.items():
        promo_link = all_links_dict.get(target_url)
        generated_links[offer_key] = promo_link
        if not promo_link:
            logger.warning(f"Failed to get affiliate link for offer {offer_key} (target: {target_url})")

    return generated_links

def _build_response_message(product_data: dict, generated_links: dict, details_source: str) -> str:
    message_lines = []
    product_title = product_data.get('title', 'Unknown Product')
    product_price = product_data.get('price')
    product_currency = product_data.get('currency', '')

    message_lines.append(f"<b>{product_title[:250]}</b>")

    if details_source == "API" and product_price:
        price_str = f"{product_price} {product_currency}".strip()
        message_lines.append(f"\n💰 <b>Price:</b> {price_str}\n")
    elif details_source == "Scraped":
        message_lines.append("\n💰 <b>Price:</b> Unavailable (Scraped)\n")
    else:
        message_lines.append("\n❌ <b>Product details unavailable</b>\n")

    message_lines.append("🎁 <b>Special Offers:</b>")
    message_lines.append("──────────────\n")

    offers_available = False
    for offer_key in OFFER_ORDER:
        link = generated_links.get(offer_key)
        offer_name = OFFER_PARAMS[offer_key]["name"]
        if link:
            message_lines.append(f'▫️ {offer_name}: <a href="{link}">Get Discount</a>\n')
            offers_available = True
        else:
            message_lines.append(f"▫️ {offer_name}: ❌ Not Available")

    if not offers_available:
         message_lines = [f"<b>{product_title[:250]}</b>\n\nWe couldn't find an offer for this product."]


    if offers_available:
        message_lines.append("──────────────")
        message_lines.append("\n🔔 <b>Follow Us:</b>")
        message_lines.append("📱 Telegram: @Aliexpress_Deal_Dz")
        message_lines.append(f"💻 GitHub: <a href='https://github.com/ReizoZ'>ReizoZ</a>")
        message_lines.append("🤝 Discord: Join Our Community")
        message_lines.append("\n<i>By RizoZ - Deals Bot</i>")

    return "\n".join(message_lines)

def _build_reply_markup() -> InlineKeyboardMarkup:
     keyboard = [
        [
            InlineKeyboardButton("🎯 Choice Day", url="https://s.click.aliexpress.com/e/_oCPK1K1"),
            InlineKeyboardButton("🔥 Best Deals", url="https://s.click.aliexpress.com/e/_onx9vR3")
        ],
        [
            InlineKeyboardButton("💻 GitHub", url="https://github.com/ReizoZ"),
            InlineKeyboardButton("🎮 Discord", url="https://discord.gg/9QzECYfmw8"),
            InlineKeyboardButton("📱 Channel", url="https://t.me/Aliexpress_Deal_Dz")
        ],
        [
            InlineKeyboardButton("☕ Support Me", url="https://ko-fi.com/reizoz")
        ]
    ]
     return InlineKeyboardMarkup(keyboard)

async def _send_telegram_response(context: ContextTypes.DEFAULT_TYPE, chat_id: int, product_data: dict, message_text: str, reply_markup: InlineKeyboardMarkup):
    product_image = product_data.get('image_url')
    product_id = product_data.get('id', 'N/A') 

    try:
        if product_image and "couldn't find an offer" not in message_text: 
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=product_image,
                caption=message_text,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup
            )
        else:
            await context.bot.send_message(
                chat_id=chat_id,
                text=message_text,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
                reply_markup=reply_markup
            )
    except Exception as send_error:
        logger.error(f"Failed to send message for product {product_id} to chat {chat_id}: {send_error}")
        # Fallback message if sending fails
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"⚠️ Error displaying product {product_id}. Please try again or check the logs.",
                reply_markup=reply_markup # Still provide buttons if possible
            )
        except Exception as fallback_error:
             logger.error(f"Failed to send fallback error message for product {product_id} to chat {chat_id}: {fallback_error}")


async def process_product_telegram(product_id: str, base_url: str, update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    logger.info(f"Processing Product ID: {product_id} for chat {chat_id}")

    try:
        product_data, details_source = await _get_product_data(product_id)
        if not product_data:
             # Should not happen with current _get_product_data logic, but handle defensively
             logger.error(f"Failed to get any product data (API or Scraped) for {product_id}")
             await context.bot.send_message(chat_id=chat_id, text=f"Could not retrieve data for product ID {product_id}.")
             return

        product_data['id'] = product_id # Add ID for logging in send function

        generated_links = await _generate_offer_links(base_url)

        response_text = _build_response_message(product_data, generated_links, details_source)
        reply_markup = _build_reply_markup()

        await _send_telegram_response(context, chat_id, product_data, response_text, reply_markup)

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
    if not update.message or not update.message.text:
        return

    message_text = update.message.text
    user = update.effective_user
    chat_id = update.effective_chat.id
    logger.info(f"Received message from {user.username or user.id} in chat {chat_id}")

    potential_urls = extract_potential_aliexpress_urls(message_text)
    if not potential_urls:
        await context.bot.send_message(
            chat_id=chat_id,
            text="❌ No AliExpress links found. Please send a valid AliExpress product link."
        )
        return

    logger.info(f"Found {len(potential_urls)} potential URLs in message from {user.username or user.id}")

    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    loading_sticker_msg = None
    try:
        loading_sticker_msg = await context.bot.send_sticker(chat_id, "CAACAgIAAxkBAAIU1GYOk5jWvCvtykd7TZkeiFFZRdUYAAIjAAMoD2oUJ1El54wgpAY0BA")
    except Exception as sticker_err:
        logger.warning(f"Could not send loading sticker: {sticker_err}")


    processed_product_ids = set()
    tasks = []
    async with aiohttp.ClientSession() as session:
        for url in potential_urls:
            original_url = url
            product_id = None
            base_url = None

            if not url.startswith(('http://', 'https://')):
                 if COMBINED_DOMAIN_REGEX.search(url): # Use combined regex here
                    logger.debug(f"Prepending https:// to potential URL: {url}")
                    url = f"https://{url}"
                 else:
                    logger.debug(f"Skipping potential URL without scheme or known AE domain: {original_url}")
                    continue

            if STANDARD_ALIEXPRESS_DOMAIN_REGEX.match(url):
                product_id = extract_product_id(url)
                if product_id:
                    base_url = clean_aliexpress_url(url, product_id)
                    logger.debug(f"Standard URL: {url} -> ID: {product_id}, Base: {base_url}")

            elif SHORT_LINK_DOMAIN_REGEX.match(url):
                logger.debug(f"Potential short link: {url}")
                final_url = await resolve_short_link(url, session)
                if final_url:
                    product_id = extract_product_id(final_url)
                    if product_id:
                        base_url = clean_aliexpress_url(final_url, product_id)
                        logger.debug(f"Resolved short link: {url} -> {final_url} -> ID: {product_id}, Base: {base_url}")
                else:
                     logger.warning(f"Could not resolve or extract ID from short link: {original_url}")

            if product_id and base_url and product_id not in processed_product_ids:
                processed_product_ids.add(product_id)
                tasks.append(process_product_telegram(product_id, base_url, update, context))
            elif product_id and product_id in processed_product_ids:
                 logger.debug(f"Skipping duplicate product ID: {product_id}")

    if not tasks:
        logger.info(f"No processable AliExpress product links found after filtering/resolution.")
        await context.bot.send_message(
            chat_id=chat_id,
            text="❌ We couldn't find any valid AliExpress product links in your message."
        )
    else:
        if len(tasks) > 1:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"⏳ Processing {len(tasks)} AliExpress products. Please wait..."
            )
        logger.info(f"Processing {len(tasks)} unique AliExpress products for chat {chat_id}")
        await asyncio.gather(*tasks)

    if loading_sticker_msg:
        try:
            await context.bot.delete_message(chat_id, loading_sticker_msg.message_id)
        except Exception as delete_err:
            logger.warning(f"Could not delete loading sticker: {delete_err}")


def main() -> None:
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))

    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.Regex(COMBINED_DOMAIN_REGEX),
        handle_message
    ))

    application.add_handler(MessageHandler(
        filters.FORWARDED & filters.TEXT & filters.Regex(COMBINED_DOMAIN_REGEX),
        handle_message
    ))

    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & ~filters.Regex(COMBINED_DOMAIN_REGEX),
        lambda update, context: context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Please send an AliExpress product link to generate affiliate links."
        )
    ))

    job_queue = application.job_queue
    job_queue.run_once(periodic_cache_cleanup, 60)
    job_queue.run_repeating(periodic_cache_cleanup, interval=timedelta(days=1), first=timedelta(days=1))

    logger.info("Starting Telegram bot polling...")
    logger.info(f"Using AliExpress Key: {ALIEXPRESS_APP_KEY[:4]}...")
    logger.info(f"Using Tracking ID: {ALIEXPRESS_TRACKING_ID}")
    logger.info(f"Settings: Currency={TARGET_CURRENCY}, Lang={TARGET_LANGUAGE}, Country={QUERY_COUNTRY}")
    logger.info(f"Cache expiry: {CACHE_EXPIRY_DAYS} days")
    offer_names = [v['name'] for k, v in OFFER_PARAMS.items()]
    logger.info(f"Offers: {', '.join(offer_names)}")
    logger.info("Bot is ready and listening...")

    application.run_polling()

    logger.info("Shutting down thread pool...")
    executor.shutdown(wait=True)
    logger.info("Bot stopped.")

if __name__ == "__main__":
    main()









































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

# In[2]:

bot = telebot.TeleBot('7851686998:AAE__oayqocUnTcv9QPoo5FArcjQ5Ky11D8')
  
aliexpress = AliexpressApi('506592', 'ggkzfJ7lilLc7OXs6khWfT4qTZdZuJbh',
                           models.Language.EN, models.Currency.EUR, 'default')
# In[3]:

keyboardStart = types.InlineKeyboardMarkup(row_width=1)
btn1 = types.InlineKeyboardButton("⭐️ألعاب لجمع العملات المعدنية⭐️",
                                  callback_data="games")
btn2 = types.InlineKeyboardButton("⭐️تخفيض العملات على منتجات السلة 🛒⭐️",
                                  callback_data='click')

btn4 = types.InlineKeyboardButton("🎬 شاهد كيفية عمل البوت 🎬",
                                  url="https://t.me/AliXPromotion/8")
btn5 = types.InlineKeyboardButton(
    "💰  حمل تطبيق Aliexpress عبر الضغط هنا للحصول على مكافأة 5 دولار  💰",
    url="https://a.aliexpress.com/_mtV0j3q")
keyboardStart.add(btn1, btn2, btn3, btn4, btn5)

keyboard = types.InlineKeyboardMarkup(row_width=1)
btn1 = types.InlineKeyboardButton("⭐️ألعاب لجمع العملات المعدنية⭐️",
                                  callback_data="games")
btn2 = types.InlineKeyboardButton("⭐️تخفيض العملات على منتجات السلة 🛒⭐️",
                                  callback_data='click')
btn3 = types.InlineKeyboardButton("❤️ اشترك في القناة للمزيد من العروض ❤️",
                                  url="https://t.me/AliXPromotion")

keyboard.add(btn1, btn2, btn3)

keyboard_games = types.InlineKeyboardMarkup(row_width=1)
btn1 = types.InlineKeyboardButton(
    " ⭐️ صفحة مراجعة وجمع النقاط يوميا ⭐️",
    url="https://s.click.aliexpress.com/e/_on0MwkF")
btn2 = types.InlineKeyboardButton(
    "⭐️ لعبة Merge boss ⭐️", url="https://s.click.aliexpress.com/e/_DlCyg5Z")
btn3 = types.InlineKeyboardButton(
    "⭐️ لعبة Fantastic Farm ⭐️",
    url="https://s.click.aliexpress.com/e/_DBBkt9V")
btn4 = types.InlineKeyboardButton(
    "⭐️ لعبة قلب الاوراق Flip ⭐️",
    url="https://s.click.aliexpress.com/e/_DdcXZ2r")
btn5 = types.InlineKeyboardButton(
    "⭐️ لعبة GoGo Match ⭐️", url="https://s.click.aliexpress.com/e/_DDs7W5D")
keyboard_games.add(btn1, btn2, btn3, btn4, btn5)

# In[4]:


@bot.message_handler(commands=['start'])
def welcome_user(message):
  bot.send_message(
      message.chat.id,
      "مرحبا بك، ارسل لنا رابط المنتج الذي تريد شرائه لنوفر لك افضل سعر له 👌 \n",
      reply_markup=keyboardStart)


@bot.callback_query_handler(func=lambda call: call.data == 'click')
def button_click(callback_query):
  bot.edit_message_text(chat_id=callback_query.message.chat.id,
                        message_id=callback_query.message.message_id,
                        text="...")

  # Send a message with text
  #bot.send_message(callback_query.message.chat.id, "This is the message text.")

  text = "✅1-ادخل الى السلة من هنا:\n" \
         " https://s.click.aliexpress.com/e/_opGCtMf \n" \
         "✅2-قم باختيار المنتجات التي تريد تخفيض سعرها\n" \
         "✅3-اضغط على زر دفع ليحولك لصفحة التأكيد \n" \
         "✅4-اضغط على الايقونة في الاعلى وانسخ الرابط  هنا في البوت لتتحصل على رابط التخفيض"

  img_link1 = "https://i.postimg.cc/HkMxWS1T/photo-5893070682508606111-y.jpg"
  bot.send_photo(callback_query.message.chat.id,
                 img_link1,
                 caption=text,
                 reply_markup=keyboard)


# In[5]:


def get_affiliate_links(message, message_id, link):
  try:

  
    limit_links = aliexpress.get_affiliate_links(
        f'https://star.aliexpress.com/share/share.htm?platform=AE&businessType=ProductDetail&redirectUrl={link}?sourceType=561&aff_fcid='
    )
    limit_links = limit_links[0].promotion_link

    try:
      img_link = aliexpress.get_products_details([
          '1000006468625',
          f'https://star.aliexpress.com/share/share.htm?platform=AE&businessType=ProductDetail&redirectUrl={link}'
      ])
      price_pro = img_link[0].target.sale_price
      title_link = img_link[0].product_title
      img_link = img_link[0].product_main_image_url
      print(img_link)
      bot.delete_message(message.chat.id, message_id)
      bot.send_photo(message.chat.id,
                     img_link,
                     caption=" \n🛒 منتجك هو  : 🔥 \n"
                     f" {title_link} 🛍 \n"
                     f"  سعر المنتج  : "
                     f" {price_pro}  دولار 💵\n"
                     " \n قارن بين الاسعار واشتري 🔥 \n"
                     "💰 عرض العملات (السعر النهائي عند الدفع)  : \n"
                     f"الرابط {affiliate_link} \n"
                     f"💎 عرض السوبر  : \n"
                     f"الرابط {super_links} \n"
                     f"♨️ عرض محدود  : \n"
                     f"الرابط {limit_links} \n\n"
                     "#AliXPromotion ✅",
                     reply_markup=keyboard)

    except:

      bot.delete_message(message.chat.id, message_id)
      bot.send_message(message.chat.id, "قارن بين الاسعار واشتري 🔥 \n"
                       "💰 عرض العملات (السعر النهائي عند الدفع) : \n"
                       f"الرابط {affiliate_link} \n"
                       f"💎 عرض السوبر : \n"
                       f"الرابط {super_links} \n"
                       f"♨️ عرض محدود : \n"
                       f"الرابط {limit_links} \n\n"
                       "#AliXPromotion ✅",
                       reply_markup=keyboard)

  except:
    bot.send_message(message.chat.id, "حدث خطأ 🤷🏻‍♂️")


# In[6]:
def extract_link(text):
  # Regular expression pattern to match links
  link_pattern = r'https?://\S+|www\.\S+'

  # Find all occurrences of the pattern in the text
  links = re.findall(link_pattern)

  if links:
    return links[0]


def build_shopcart_link(link):
  params = get_url_params(link)
  shop_cart_link = "https://www.aliexpress.com/p/trade/confirm.html?"
  shop_cart_params = {
      "availableProductShopcartIds":
      ",".join(params["availableProductShopcartIds"]),
      "extraParams":
      json.dumps({"channelInfo": {
          "sourceType": "620"
      }}, separators=(',', ':'))
  }
  return create_query_string_url(link=shop_cart_link, params=shop_cart_params)


def get_url_params(link):
  parsed_url = urlparse(link)
  params = parse_qs(parsed_url.query)
  return params


def create_query_string_url(link, params):
  return link + urllib.parse.urlencode(params)


## Shop cart Affiliate تخفيض السلة
def get_affiliate_shopcart_link(link, message):
  try:
    shopcart_link = build_shopcart_link(link)
    affiliate_link = aliexpress.get_affiliate_links(
        shopcart_link)[0].promotion_link

    text2 = f"هذا رابط تخفيض السلة \n" \
           f"{str(affiliate_link)}" \

    img_link3 = "https://i.postimg.cc/HkMxWS1T/photo-5893070682508606111-y.jpg"
    bot.send_photo(message.chat.id, img_link3, caption=text2)

  except:
    bot.send_message(message.id, "حدث خطأ 🤷🏻‍♂️")


@bot.message_handler(func=lambda message: True)
def get_link(message):
  link = extract_link(message.text)

  sent_message = bot.send_message(message.chat.id,
                                  'المرجو الانتظار قليلا، يتم تجهيز العروض ⏳')
  message_id = sent_message.message_id
  if link and "aliexpress.com" in link and not ("p/shoppingcart"
                                                in message.text.lower()):
    if "availableProductShopcartIds".lower() in message.text.lower():
      get_affiliate_shopcart_link(link, message)
      return
    get_affiliate_links(message, message_id, link)

  else:
    bot.delete_message(message.chat.id, message_id)
    bot.send_message(message.chat.id,
                     "الرابط غير صحيح ! تأكد من رابط المنتج أو اعد المحاولة.\n"
                     " قم بإرسال <b> الرابط فقط</b> بدون عنوان المنتج",
                     parse_mode='HTML')


# In[7]:


@bot.callback_query_handler(func=lambda call: True)
def handle_callback_query(call):
  bot.send_message(call.message.chat.id, "..")

  img_link2 = "https://i.postimg.cc/zvDbVTS0/photo-5893070682508606110-x.jpg"
  bot.send_photo(
      call.message.chat.id,
      img_link2,
      caption=
      "روابط ألعاب جمع العملات المعدنية لإستعمالها في خفض السعر لبعض المنتجات، قم بالدخول يوميا لها للحصول على أكبر عدد ممكن في اليوم 👇",
      reply_markup=keyboard_games)

  # In[ ]:


keep_alive()

infinity_polling(timeout=10, long_polling_timeout=5)
