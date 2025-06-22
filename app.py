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

# Configuration améliorée
load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
ALIEXPRESS_APP_KEY = os.getenv('ALIEXPRESS_APP_KEY')
ALIEXPRESS_APP_SECRET = os.getenv('ALIEXPRESS_APP_SECRET')
TRACKING_ID = os.getenv('ALIEXPRESS_TRACKING_ID', 'default')
API_URL = 'https://api-sg.aliexpress.com/sync'
QUERY_FIELDS = 'product_main_image_url,target_sale_price,product_title,target_sale_price_currency,shop_url,shop_name'

# Optimisation du logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)

# Vérification des variables d'environnement
if not all([TELEGRAM_BOT_TOKEN, ALIEXPRESS_APP_KEY, ALIEXPRESS_APP_SECRET]):
    logger.error("Configuration manquante")
    exit()

class AliExpressBot:
    def __init__(self):
        self.client = iop.IopClient(API_URL, ALIEXPRESS_APP_KEY, ALIEXPRESS_APP_SECRET)
        self.executor = ThreadPoolExecutor(max_workers=10)
        self.session = aiohttp.ClientSession()
        self.cache = {
            'products': {},
            'links': {},
            'resolved_urls': {}
        }

    async def resolve_url(self, short_url: str) -> str:
        """Résout les URLs courtes"""
        if short_url in self.cache['resolved_urls']:
            return self.cache['resolved_urls'][short_url]

        try:
            async with self.session.get(short_url, allow_redirects=True, timeout=10) as resp:
                final_url = str(resp.url)
                self.cache['resolved_urls'][short_url] = final_url
                return final_url
        except Exception as e:
            logger.error(f"URL resolution failed: {e}")
            return None

    async def get_product_data(self, product_id: str) -> dict:
        """Récupère les données produit"""
        if product_id in self.cache['products']:
            return self.cache['products'][product_id]

        try:
            request = iop.IopRequest('aliexpress.affiliate.productdetail.get')
            request.add_api_param('fields', QUERY_FIELDS)
            request.add_api_param('product_ids', product_id)
            request.add_api_param('tracking_id', TRACKING_ID)
            
            response = await asyncio.get_event_loop().run_in_executor(
                self.executor, 
                lambda: self.client.execute(request)
            )
            
            data = json.loads(response.body) if isinstance(response.body, str) else response.body
            product = data.get('aliexpress_affiliate_productdetail_get_response', {}).get('resp_result', {}).get('result', {}).get('products', {}).get('product', [{}])[0]
            
            product_data = {
                'title': product.get('product_title'),
                'price': product.get('target_sale_price'),
                'currency': product.get('target_sale_price_currency'),
                'image': product.get('product_main_image_url'),
                'shop': {
                    'name': product.get('shop_name'),
                    'url': product.get('shop_url')
                }
            }
            
            self.cache['products'][product_id] = product_data
            return product_data
            
        except Exception as e:
            logger.error(f"API Error: {e}")
            return None

    async def generate_links(self, product_id: str) -> dict:
        """Génère tous les liens affiliés"""
        base_url = f"https://www.aliexpress.com/item/{product_id}.html"
        
        links = {
            'standard': await self._generate_link(base_url),
            'coin': await self._generate_link(base_url, {'sourceType': '620', 'channel': 'coin'}),
            'bundle': await self._generate_link(base_url, {'sourceType': '570'})
        }
        
        return links

    async def _generate_link(self, url: str, params: dict = None) -> str:
        """Génère un lien affilié"""
        if params is None:
            params = {}
            
        params.update({
            'aff_platform': 'api-new-link-generate',
            'aff_trace_key': TRACKING_ID
        })
        
        parsed = urlparse(url)
        return urlunparse((
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            urlencode(params),
            parsed.fragment
        ))

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Gère les messages entrants"""
        url = update.message.text
        
        # Extraction de l'ID produit
        product_id = re.search(r'(?:productIds=|/item/|/product/)(\d+)', url)
        if not product_id:
            await update.message.reply_text("❌ Lien AliExpress non valide")
            return
            
        product_id = product_id.group(1)
        
        # Récupération des données
        product = await self.get_product_data(product_id)
        if not product:
            await update.message.reply_text("❌ Impossible de récupérer les données du produit")
            return
            
        # Génération des liens
        links = await self.generate_links(product_id)
        
        # Préparation de la réponse
        message = [
            f"🛍️ *{product['title']}*",
            f"💰 Prix: *{product['price']} {product['currency']}*",
            f"🏪 Boutique: [{product['shop']['name']}]({product['shop']['url']})",
            "",
            "🔗 *Liens d'achat:*",
            f"• [Lien Standard]({links['standard']})",
            f"• [Offre Coins 🪙]({links['coin']})",
            f"• [Offre Bundle 📦]({links['bundle']})"
        ]
        
        keyboard = [
            [InlineKeyboardButton("🛒 Acheter", url=links['coin'])],
            [InlineKeyboardButton("📢 Notre Chaîne", url="https://t.me/yourchannel")]
        ]
        
        await update.message.reply_photo(
            photo=product['image'],
            caption="\n".join(message),
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

def main():
    bot = AliExpressBot()
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    app.add_handler(MessageHandler(
        filters.TEXT & filters.Regex(r'aliexpress\.com'),
        bot.handle_message
    ))
    
    app.run_polling()

if __name__ == '__main__':
    main()
