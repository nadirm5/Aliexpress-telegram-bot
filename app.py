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

# Configuration initiale
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
ALIEXPRESS_APP_KEY = os.getenv('ALIEXPRESS_APP_KEY')
ALIEXPRESS_APP_SECRET = os.getenv('ALIEXPRESS_APP_SECRET')
TARGET_CURRENCY = os.getenv('TARGET_CURRENCY', 'USD')
TARGET_LANGUAGE = os.getenv('TARGET_LANGUAGE', 'en')
QUERY_COUNTRY = os.getenv('QUERY_COUNTRY', 'US')
ALIEXPRESS_TRACKING_ID = os.getenv('ALIEXPRESS_TRACKING_ID', 'default')
ALIEXPRESS_API_URL = 'https://api-sg.aliexpress.com/sync'
QUERY_FIELDS = ('product_main_image_url,target_sale_price,product_title,'
                'target_sale_price_currency,coin_price,seller_id,product_id')
CACHE_EXPIRY_DAYS = 1
MAX_WORKERS = 10

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Initialisation client API
try:
    aliexpress_client = iop.IopClient(ALIEXPRESS_API_URL, ALIEXPRESS_APP_KEY, ALIEXPRESS_APP_SECRET)
except Exception as e:
    logger.exception("API Client init failed")
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

### Commandes du bot ###
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_html(
        "🛍️ <b>AliExpress Coin Deals Bot</b> 🪙\n\n"
        "🔍 <b>How to use:</b>\n"
        "/search [product] - Find best coin deals\n"
        "Or send any AliExpress link\n\n"
        "💡 <i>Get products with maximum coin discounts!</i>"
    )

async def search_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = ' '.join(context.args)
    if not query:
        await update.message.reply_text("Please enter a product name")
        return

    await update.message.reply_chat_action(ChatAction.TYPING)

    try:
        # Paramètres de recherche dynamiques
        random_page = str(random.randint(1, 5))
        sort_method = random.choice(['coin_desc', 'volume_desc'])  # Alterner entre coins et popularité

        def _execute_search():
            req = iop.IopRequest('aliexpress.affiliate.product.query')
            req.add_api_param('keywords', query)
            req.add_api_param('target_currency', TARGET_CURRENCY)
            req.add_api_param('tracking_id', ALIEXPRESS_TRACKING_ID)
            req.add_api_param('fields', QUERY_FIELDS)
            req.add_api_param('page_size', '5')
            req.add_api_param('page_no', random_page)
            req.add_api_param('sort', sort_method)
            return aliexpress_client.execute(req)

        response = await asyncio.get_event_loop().run_in_executor(executor, _execute_search)

        if not response or not response.body:
            await update.message.reply_text("⚠️ No results found")
            return

        data = json.loads(response.body) if isinstance(response.body, str) else response.body
        products = data.get('aliexpress_affiliate_product_query_response', {})\
                      .get('resp_result', {})\
                      .get('result', {})\
                      .get('products', {})\
                      .get('product', [])

        if not products:
            await update.message.reply_text("❌ No products with coins found")
            return

        # Envoi des résultats
        for product in products[:5]:
            await send_product_result(update, context, product)

    except Exception as e:
        logger.error(f"Search failed: {e}")
        await update.message.reply_text("🚨 Error processing your request")

async def send_product_result(update: Update, context: ContextTypes.DEFAULT_TYPE, product: dict):
    product_id = product.get('product_id')
    title = product.get('product_title', 'No Title')[:80]
    price = product.get('target_sale_price', 'N/A')
    coin_price = product.get('coin_price', price)
    image_url = product.get('product_main_image_url')
    product_url = f"https://www.aliexpress.com/item/{product_id}.html"

    # Génération lien affilié
    affiliate_link = (await generate_affiliate_links_batch([product_url])).get(product_url, product_url)

    # Formatage du message
    caption = (
        f"🪙 <b>{title}</b>\n\n"
        f"💰 <b>Price:</b> {price} → <b>{coin_price} with coins</b>\n"
        f"🔗 <a href='{affiliate_link}'>GET DEAL</a>"
    )

    # Envoi avec image si disponible
    try:
        if image_url:
            await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=image_url,
                caption=caption,
                parse_mode=ParseMode.HTML
            )
        else:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=caption,
                parse_mode=ParseMode.HTML
            )
    except Exception as e:
        logger.error(f"Failed to send product: {e}")

async def generate_affiliate_links_batch(urls: list[str]) -> dict[str, str]:
    results = {}
    uncached = []

    # Vérification cache
    for url in urls:
        cached = await link_cache.get(url)
        if cached:
            results[url] = cached
        else:
            uncached.append(url)

    if uncached:
        try:
            req = iop.IopRequest('aliexpress.affiliate.link.generate')
            req.add_api_param('promotion_link_type', '0')
            req.add_api_param('source_values', ','.join(uncached))
            req.add_api_param('tracking_id', ALIEXPRESS_TRACKING_ID)

            resp = await asyncio.get_event_loop().run_in_executor(executor, aliexpress_client.execute, req)
            
            if resp and resp.body:
                data = json.loads(resp.body) if isinstance(resp.body, str) else resp.body
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
                            results[source] = promo
                            await link_cache.set(source, promo)
        except Exception as e:
            logger.error(f"Link generation failed: {e}")
            results.update({url: url for url in uncached})

    return results

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.text:
        text = update.message.text.strip()
        
        # Détection liens AliExpress
        if re.search(r'aliexpress\.com', text, re.I):
            # Traitement des liens produits
            pass
        elif not text.startswith('/'):
            await search_products(update, context)

def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Commandes
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("search", search_products))
    
    # Messages
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot starting...")
    app.run_polling()

if __name__ == "__main__":
    main()
