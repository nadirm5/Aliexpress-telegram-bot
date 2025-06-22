import logging
import os
import re
import json
import asyncio
import time
from datetime import datetime, timedelta
from urllib.parse import urlparse, urlunparse, urlencode, parse_qsl
from concurrent.futures import ThreadPoolExecutor
import aiohttp
from dotenv import load_dotenv

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, JobQueue
from telegram.constants import ParseMode, ChatAction

import iop
from aliexpress_utils import get_product_details_by_id

# Chargement des variables d'environnement
load_dotenv()

# Configuration initiale
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

# Configuration du logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Expressions régulières
COIN_LINK_REGEX = re.compile(
    r'https?:\/\/(?:[a-z]+\.)?aliexpress\.com\/p\/coin-index\/index\.html\?(?:[^\s<>"]*&)?productIds=([\d,]+)',
    re.IGNORECASE
)

PRODUCT_ID_REGEX = re.compile(r'/item/(\d+)\.html', re.IGNORECASE)

STANDARD_ALIEXPRESS_DOMAIN_REGEX = re.compile(
    r'https?://(?!a\.|s\.click\.)([\w-]+\.)?aliexpress\.(com|ru|es|fr|pt|it|pl|nl|co\.kr|co\.jp|com\.br|com\.tr|com\.vn|us|id|th|ar)(?:\.[\w-]+)?(/.*)?',
    re.IGNORECASE
)

SHORT_LINK_DOMAIN_REGEX = re.compile(
    r'https?://(?:s\.click\.aliexpress\.com/e/|a\.aliexpress\.com/_)[a-zA-Z0-9_-]+/?',
    re.IGNORECASE
)

# Initialisation du client AliExpress
try:
    aliexpress_client = iop.IopClient(ALIEXPRESS_API_URL, ALIEXPRESS_APP_KEY, ALIEXPRESS_APP_SECRET)
except Exception as e:
    logger.exception(f"Error initializing AliExpress API client: {e}")
    exit()

executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)

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
                    return item
                else:
                    del self.cache[key]
            return None

    async def set(self, key, value):
        async with self._lock:
            self.cache[key] = (value, time.time())

    async def clear_expired(self):
        async with self._lock:
            current_time = time.time()
            expired_keys = [k for k, (_, t) in self.cache.items() if current_time - t >= self.expiry_seconds]
            for key in expired_keys:
                del self.cache[key]
            return len(expired_keys)

product_cache = CacheWithExpiry(CACHE_EXPIRY_SECONDS)
link_cache = CacheWithExpiry(CACHE_EXPIRY_SECONDS)
resolved_url_cache = CacheWithExpiry(CACHE_EXPIRY_SECONDS)

async def generate_coin_link(coin_url: str) -> str:
    """Generate affiliate link for coin URLs while preserving all parameters"""
    parsed = urlparse(coin_url)
    query = dict(parse_qsl(parsed.query))
    
    query.update({
        'aff_platform': 'api-new-link-generate',
        'aff_trace_key': ALIEXPRESS_TRACKING_ID,
        'terminal_id': str(int(time.time()))
    })
    
    new_url = urlunparse((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        parsed.params,
        urlencode(query),
        parsed.fragment
    ))
    
    links = await generate_affiliate_links_batch([new_url])
    return links.get(new_url, new_url)

async def generate_affiliate_links_batch(target_urls: list[str]) -> dict[str, str]:
    results = {}
    uncached_urls = []

    for url in target_urls:
        cached = await link_cache.get(url)
        if cached:
            results[url] = cached
        else:
            uncached_urls.append(url)

    if not uncached_urls:
        return results

    def _execute_api():
        try:
            request = iop.IopRequest('aliexpress.affiliate.link.generate')
            request.add_api_param('promotion_link_type', '0')
            request.add_api_param('source_values', ",".join(uncached_urls))
            request.add_api_param('tracking_id', ALIEXPRESS_TRACKING_ID)
            return aliexpress_client.execute(request)
        except Exception as e:
            logger.error(f"API error: {e}")
            return None

    response = await asyncio.get_event_loop().run_in_executor(executor, _execute_api)

    if response and response.body:
        try:
            data = json.loads(response.body) if isinstance(response.body, str) else response.body
            links = data.get('aliexpress_affiliate_link_generate_response', {}).get('resp_result', {}).get('result', {}).get('promotion_links', {}).get('promotion_link', [])
            
            for link in links:
                if isinstance(link, dict):
                    source = link.get('source_value')
                    promo = link.get('promotion_link')
                    if source and promo:
                        results[source] = promo
                        await link_cache.set(source, promo)
        except Exception as e:
            logger.error(f"Error parsing response: {e}")

    return results

async def fetch_product_details(product_id: str) -> dict:
    cached = await product_cache.get(product_id)
    if cached:
        return cached

    def _execute_api():
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
            logger.error(f"API error: {e}")
            return None

    response = await asyncio.get_event_loop().run_in_executor(executor, _execute_api)

    if not response or not response.body:
        return None

    try:
        data = json.loads(response.body) if isinstance(response.body, str) else response.body
        product = data.get('aliexpress_affiliate_productdetail_get_response', {}).get('resp_result', {}).get('result', {}).get('products', {}).get('product', [{}])[0]
        
        product_info = {
            'image_url': product.get('product_main_image_url'),
            'price': product.get('target_sale_price'),
            'currency': product.get('sale_price_currency', TARGET_CURRENCY),
            'title': product.get('product_title', f'Product {product_id}')
        }
        
        await product_cache.set(product_id, product_info)
        return product_info
    except Exception as e:
        logger.error(f"Error parsing product data: {e}")
        return None

async def process_coin_link(coin_url: str, update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    match = COIN_LINK_REGEX.search(coin_url)
    
    if not match:
        await context.bot.send_message(chat_id, "❌ Format de lien Coin invalide")
        return
    
    product_ids = match.group(1).split(',')
    if not product_ids:
        await context.bot.send_message(chat_id, "❌ Aucun ID produit trouvé dans le lien Coin")
        return
    
    main_product_id = product_ids[0]
    coin_affiliate_link = await generate_coin_link(coin_url)
    product_data = await fetch_product_details(main_product_id)
    
    if not product_data:
        await context.bot.send_message(chat_id, "❌ Impossible de récupérer les détails du produit")
        return
    
    # Generate standard product link
    product_url = f"https://www.aliexpress.com/item/{main_product_id}.html"
    product_links = await generate_affiliate_links_batch([product_url])
    product_affiliate_link = product_links.get(product_url, product_url)
    
    # Prepare response
    message = [
        f"✨ <b>{product_data['title']}</b> ✨",
        f"\n💰 <b>Prix: {product_data['price']} {product_data['currency']}</b>",
        f"\n🪙 <b>Lien Coin Offer (recommandé):</b>",
        f"{coin_affiliate_link}",
        f"\n🛒 <b>Lien Produit Standard:</b>",
        f"{product_affiliate_link}",
        f"\n\n💡 <i>Le lien Coin conserve tous les avantages et réductions</i>"
    ]
    
    keyboard = [
        [InlineKeyboardButton("🛒 Acheter via Coin Offer", url=coin_affiliate_link)],
        [InlineKeyboardButton("📢 Notre Chaîne", url="https://t.me/RayanCoupon")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if product_data['image_url']:
        await context.bot.send_photo(
            chat_id=chat_id,
            photo=product_data['image_url'],
            caption="\n".join(message),
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup
        )
    else:
        await context.bot.send_message(
            chat_id=chat_id,
            text="\n".join(message),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
            reply_markup=reply_markup
        )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    message_text = update.message.text
    chat_id = update.effective_chat.id
    
    # Check for coin links first
    if COIN_LINK_REGEX.search(message_text):
        await process_coin_link(message_text, update, context)
        return
    
    # Existing URL processing for other links...
    # (Keep your existing handle_message implementation for standard links)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Bienvenue sur le bot AliExpress!\n\n"
        "Envoyez-moi un lien produit AliExpress ou un lien Coin Offer "
        "pour obtenir les meilleurs prix avec tracking affilié."
    )

async def periodic_cache_cleanup(context: ContextTypes.DEFAULT_TYPE):
    expired = await product_cache.clear_expired()
    expired += await link_cache.clear_expired()
    expired += await resolved_url_cache.clear_expired()
    logger.info(f"Cache cleanup: removed {expired} expired items")

def main():
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & 
        (filters.Regex(COIN_LINK_REGEX) |
        filters.Regex(STANDARD_ALIEXPRESS_DOMAIN_REGEX) |
        filters.Regex(SHORT_LINK_DOMAIN_REGEX)),
        handle_message
    ))
    
    job_queue = application.job_queue
    if job_queue:
        job_queue.run_repeating(periodic_cache_cleanup, interval=timedelta(hours=6))
    
    logger.info("Starting bot...")
    application.run_polling()

if __name__ == "__main__":
    main()
