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
STANDARD_ALIEXPRESS_DOMAIN_REGEX = re.compile(r'https?://(?!a\.|s\.click\.)([\w-]+\.)?aliexpress\.(com|ru|es|fr|pt|it|pl|nl|co\.kr|co\.jp|com\.br|com\.tr|com\.vn|us|id|th|ar)(\.[\w-]+)?(/[^\s<>"]*)?', re.IGNORECASE)
SHORT_LINK_DOMAIN_REGEX = re.compile(r'https?://(?:s\.click\.aliexpress\.com/e/|a\.aliexpress\.com/_)[a-zA-Z0-9_-]+/?', re.IGNORECASE)
COMBINED_DOMAIN_REGEX = re.compile(r'(?:https?://)?(?:www\.)?(?:aliexpress\.com|s\.click\.aliexpress\.com|a\.aliexpress\.com)', re.IGNORECASE)
OFFER_PARAMS = {
    "coin": {
        "name": "🪙 <b>🎯 Coins</b> – <b>الرابط بالتخفيض ⬇️ أقل سعر بالعملات 💸</b> 👉",
        "params": {
            "sourceType": "620%26channel=coin",
            "afSmartRedirect": "y"
        }
    }
}

OFFER_ORDER = ["coin"]
ALIEXPRESS_TRACKING_ID)
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
        "👋 مرحبًا بك في بوت خصومات علي إكسبريس! 🛍️\n\n"
        "🔍 <b>How to use:</b>\n"
        "🔍 <b>كيفية الاستخدام:</b>\n"
        "1️⃣ Copy an AliExpress product link 📋\n"
        "1️⃣ انسخ رابط منتج من علي إكسبريس 📋\n"
        "2️⃣ Send the link here 📤\n"
        "2️⃣ أرسل الرابط هنا 📤\n"
        "3️⃣ Get links back ✨\n\n"
        "3️⃣ ستحصل على روابط باقل الاسعار ✨\n\n"
        "🔗 Supports regular & short links.\n"
        "🔗 يدعم الروابط الطويلة والقصيرة.\n"
        "🚀 Send a link to start! 🎁"
          "🚀 أرسل رابطًا للبدء! 🎁"
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

    product_title = product_data.get('title', 'Unknown Product').split('\n')[0][:100]
    decorated_title = f"✨⭐️ {product_title} ⭐️✨"
    product_price = product_data.get('price')
    product_currency = product_data.get('currency', '')

    message_lines.append(f"<b>{decorated_title}</b>")

    if details_source == "API" and product_price:
        price_str = f"{product_price} {product_currency}".strip()
        message_lines.append(f"\n💰 <b>Price $السعر بدون تخفيض:</b> {price_str}\n")
    elif details_source == "Scraped":
        message_lines.append("\n💰 <b>Price:</b> Unavailable (Scraped)\n")
    else:
        message_lines.append("\n❌ <b>Product details unavailable</b>\n")

    coin_link = generated_links.get("coin")
    if coin_link:
        message_lines.append(f"✨⭐️ {product_info['title']} ⭐️✨\n")
message_lines.append(f"💰 السعر بدون تخفيض: <b>{product_info['original_price']:.2f} {product_info['currency']}</b>")
message_lines.append(f"💸 السعر بعد التخفيض: <b>{product_info['price']:.2f} {product_info['currency']}</b>")
message_lines.append(f"🎯 نسبة التخفيض: <b>{product_info['discount_percent']}٪</b>\n")
message_lines.append(f"▫️ 🪙🔥 أقل سعر على الرابط ⬇️\n<b>{coin_link}</b>")
message_lines.append("💥 خصم يصل حتى <b>70%</b> – العرض محدود، ألحق\n")
message_lines.append("🔔 <b>تابعنا</b>")
message_lines.append("📱 Telegram: @RayanCoupon")

return "\n".join(message_lines)


def _build_reply_markup() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("🎫 كوبونات  |  Coupons", url="https://s.click.aliexpress.com/e/_oliYXEJ"),
            InlineKeyboardButton("🔥 Deal of the Day", url="https://s.click.aliexpress.com/e/_omRiewZ")
        ],
        [
            InlineKeyboardButton("🛍️ Bundle Deals", url="https://s.click.aliexpress.com/e/_oE0GKJ9")
        ],
        [
            InlineKeyboardButton("📢 Join VIP Channel", url="https://t.me/RayanCoupon"),
            InlineKeyboardButton("❤️ Support Me", url="https://moneyexpress.fun")
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
