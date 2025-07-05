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

# Chargement des variables d'environnement
load_dotenv()

# Configuration initiale
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
ALIEXPRESS_APP_KEY = os.getenv('ALIEXPRESS_APP_KEY')
ALIEXPRESS_APP_SECRET = os.getenv('ALIEXPRESS_APP_SECRET')
ALIEXPRESS_TRACKING_ID = os.getenv('ALIEXPRESS_TRACKING_ID', 'default')
ALIEXPRESS_API_URL = 'https://api-sg.aliexpress.com/sync'

# Configuration du logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Vérification des variables d'environnement
if not all([TELEGRAM_BOT_TOKEN, ALIEXPRESS_APP_KEY, ALIEXPRESS_APP_SECRET]):
    logger.error("Missing required environment variables")
    exit()

# Initialisation du client AliExpress
try:
    aliexpress_client = iop.IopClient(ALIEXPRESS_API_URL, ALIEXPRESS_APP_KEY, ALIEXPRESS_APP_SECRET)
except Exception as e:
    logger.error(f"Failed to initialize AliExpress client: {e}")
    exit()

# Pool d'exécution
executor = ThreadPoolExecutor(max_workers=10)

# Expressions régulières pour le parsing des URLs
URL_REGEX = re.compile(r'https?://[^\s<>"]+|www\.[^\s<>"]+', re.IGNORECASE)
PRODUCT_ID_REGEX = re.compile(r'/item/(\d+)\.html', re.IGNORECASE)

class CacheWithExpiry:
    """Classe pour gérer le cache avec expiration"""
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

# Initialisation des caches
product_cache = CacheWithExpiry(86400)  # 1 jour
link_cache = CacheWithExpiry(86400)

async def search_aliexpress_products(query: str) -> list:
    """Recherche des produits sur AliExpress"""
    try:
        request = iop.IopRequest('aliexpress.affiliate.product.query')
        request.add_api_param('keywords', query)
        request.add_api_param('fields', 'productId,productTitle,productMainImageUrl,salePrice')
        request.add_api_param('tracking_id', ALIEXPRESS_TRACKING_ID)
        
        response = await asyncio.get_event_loop().run_in_executor(
            executor, lambda: aliexpress_client.execute(request))
        
        if not response or not response.body:
            return []
            
        data = json.loads(response.body) if isinstance(response.body, str) else response.body
        
        if 'error_response' in data:
            logger.error(f"API error: {data['error_response']}")
            return []
            
        products = data.get('aliexpress_affiliate_product_query_response', {}).get('resp_result', {}).get('result', {}).get('products', {}).get('product', [])
        
        return [{
            'id': p.get('productId'),
            'title': p.get('productTitle'),
            'image': p.get('productMainImageUrl'),
            'price': p.get('salePrice'),
            'currency': 'USD',
            'affiliate_url': f"https://s.click.aliexpress.com/e/_?tracking_id={ALIEXPRESS_TRACKING_ID}&product_id={p.get('productId')}"
        } for p in products]
        
    except Exception as e:
        logger.error(f"Search error: {e}")
        return []

async def handle_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gère la commande /search"""
    if not update.message:
        return

    query = ' '.join(context.args)
    if not query:
        await update.message.reply_text("Usage: /search <product>")
        return
    
    await update.message.reply_text(f"🔍 Searching for '{query}'...")
    
    try:
        products = await search_aliexpress_products(query)
        if not products:
            await update.message.reply_text("No products found")
            return
            
        for product in products[:3]:  # Limite à 3 résultats
            msg = f"<b>{product['title']}</b>\n💰 {product['price']} {product['currency']}\n🛒 <a href='{product['affiliate_url']}'>Buy now</a>"
            
            if product['image']:
                await update.message.reply_photo(
                    photo=product['image'],
                    caption=msg,
                    parse_mode=ParseMode.HTML
                )
            else:
                await update.message.reply_text(
                    msg,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True
                )
                
    except Exception as e:
        logger.error(f"Search failed: {e}")
        await update.message.reply_text("Error searching products")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gère la commande /start"""
    await update.message.reply_text(
        "Welcome to AliExpress Bot!\n"
        "Use /search <product> to find products"
    )

def main() -> None:
    """Point d'entrée principal"""
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("search", handle_search))
    
    # Démarrer le bot
    application.run_polling()
    logger.info("Bot started")

if __name__ == "__main__":
    main()
