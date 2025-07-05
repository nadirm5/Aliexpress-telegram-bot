import logging
import os
import re
import json
import asyncio
import random
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

# Chargement des variables d'environnement
load_dotenv()

# Configuration
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
ALIEXPRESS_APP_KEY = os.getenv('ALIEXPRESS_APP_KEY')
ALIEXPRESS_APP_SECRET = os.getenv('ALIEXPRESS_APP_SECRET')
TARGET_CURRENCY = os.getenv('TARGET_CURRENCY', 'USD')
TARGET_LANGUAGE = os.getenv('TARGET_LANGUAGE', 'en')
QUERY_COUNTRY = os.getenv('QUERY_COUNTRY', 'US')
ALIEXPRESS_TRACKING_ID = os.getenv('ALIEXPRESS_TRACKING_ID', 'default')
ALIEXPRESS_API_URL = 'https://api-sg.aliexpress.com/sync'
QUERY_FIELDS = ('product_main_image_url,target_sale_price,'
                'product_title,target_sale_price_currency,'
                'coin_price,seller_id,product_id')
CACHE_EXPIRY_DAYS = 1
MAX_WORKERS = 10

# Configuration du logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Initialisation du client AliExpress
try:
    aliexpress_client = iop.IopClient(ALIEXPRESS_API_URL, ALIEXPRESS_APP_KEY, ALIEXPRESS_APP_SECRET)
    logger.info("AliExpress API client initialized successfully")
except Exception as e:
    logger.exception("Failed to initialize AliExpress client")
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
                del self.cache[key]
            return None

    async def set(self, key, value):
        async with self._lock:
            self.cache[key] = (value, time.time())

product_cache = CacheWithExpiry(CACHE_EXPIRY_DAYS * 24 * 60 * 60)
link_cache = CacheWithExpiry(CACHE_EXPIRY_DAYS * 24 * 60 * 60)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_html(
        "👋 <b>AliExpress Coin Deals Bot</b> 🛍️\n\n"
        "🔍 <b>How to use:</b>\n"
        "/search [product] - Find products with coin discounts\n"
        "Or send any AliExpress product link\n\n"
        "🪙 Get the best deals with coins discounts!"
    )

async def search_products(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = ' '.join(context.args)
    if not query:
        await update.message.reply_text("Please enter a product to search")
        return

    await update.message.reply_chat_action(ChatAction.TYPING)
    
    try:
        # Pagination aléatoire pour varier les résultats
        random_page = str(random.randint(1, 5))
        
        def _execute_search():
            request = iop.IopRequest('aliexpress.affiliate.product.query')
            request.add_api_param('keywords', query)
            request.add_api_param('target_currency', TARGET_CURRENCY)
            request.add_api_param('tracking_id', ALIEXPRESS_TRACKING_ID)
            request.add_api_param('sort', 'coin_desc')
            request.add_api_param('fields', QUERY_FIELDS)
            request.add_api_param('page_size', '5')
            request.add_api_param('page_no', random_page)
            return aliexpress_client.execute(request)

        response = await asyncio.get_event_loop().run_in_executor(executor, _execute_search)

        if not response or not response.body:
            await update.message.reply_text("No results found for your search")
            return

        # Traitement de la réponse
        response_data = json.loads(response.body) if isinstance(response.body, str) else response.body
        products = response_data.get('aliexpress_affiliate_product_query_response', {})\
                              .get('resp_result', {})\
                              .get('result', {})\
                              .get('products', {})\
                              .get('product', [])

        if not products:
            await update.message.reply_text("No products found with coin discounts")
            return

        # Envoi des résultats
        for product in products[:5]:  # Limite à 5 résultats
            product_id = product.get('product_id')
            title = product.get('product_title', 'No Title')[:80]
            price = product.get('target_sale_price', 'N/A')
            coin_price = product.get('coin_price', price)
            image_url = product.get('product_main_image_url')
            product_url = f"https://www.aliexpress.com/item/{product_id}.html"

            # Génération du lien d'affiliation
            affiliate_links = await generate_affiliate_links_batch([product_url])
            final_url = affiliate_links.get(product_url, product_url)

            # Construction du message
            caption = (
                f"🪙 <b>{title}</b>\n"
                f"💰 <b>Price: {price} → <u>{coin_price} with coins</u></b>\n"
                f"🔗 <a href='{final_url}'>BUY NOW</a>"
            )

            if image_url:
                try:
                    await context.bot.send_photo(
                        chat_id=update.effective_chat.id,
                        photo=image_url,
                        caption=caption,
                        parse_mode=ParseMode.HTML
                    )
                except Exception as e:
                    logger.error(f"Failed to send image: {e}")
                    await context.bot.send_message(
                        chat_id=update.effective_chat.id,
                        text=caption,
                        parse_mode=ParseMode.HTML
                    )
            else:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=caption,
                    parse_mode=ParseMode.HTML
                )

    except Exception as e:
        logger.error(f"Search error: {e}")
        await update.message.reply_text("An error occurred. Please try again later.")

async def generate_affiliate_links_batch(urls: list[str]) -> dict[str, str]:
    cached_links = {}
    uncached_urls = []

    # Vérification du cache
    for url in urls:
        cached = await link_cache.get(url)
        if cached:
            cached_links[url] = cached
        else:
            uncached_urls.append(url)

    if not uncached_urls:
        return cached_links

    try:
        # Appel API pour les liens non cachés
        request = iop.IopRequest('aliexpress.affiliate.link.generate')
        request.add_api_param('promotion_link_type', '0')
        request.add_api_param('source_values', ','.join(uncached_urls))
        request.add_api_param('tracking_id', ALIEXPRESS_TRACKING_ID)

        response = await asyncio.get_event_loop().run_in_executor(executor, aliexpress_client.execute, request)
        
        if response and response.body:
            data = json.loads(response.body) if isinstance(response.body, str) else response.body
            links = data.get('aliexpress_affiliate_link_generate_response', {})\
                       .get('resp_result', {})\
                       .get('result', {})\
                       .get('promotion_links', {})\
                       .get('promotion_link', [])
            
            for link in links:
                if isinstance(link, dict):
                    source = link.get('source_value')
                    promo = link.get('promotion_link')
                    if source and promo:
                        cached_links[source] = promo
                        await link_cache.set(source, promo)

    except Exception as e:
        logger.error(f"Link generation error: {e}")

    return {**cached_links, **{url: url for url in uncached_urls if url not in cached_links}}

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message and update.message.text:
        if update.message.text.startswith('/'):
            return
        await search_products(update, context)

def main() -> None:
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Gestionnaires de commandes
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("search", search_products))
    
    # Gestionnaire de messages
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Starting bot...")
    application.run_polling()

if __name__ == "__main__":
    main()
