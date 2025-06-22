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

# Configuration initiale
load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
ALIEXPRESS_APP_KEY = os.getenv('ALIEXPRESS_APP_KEY')
ALIEXPRESS_APP_SECRET = os.getenv('ALIEXPRESS_APP_SECRET')
ALIEXPRESS_TRACKING_ID = os.getenv('ALIEXPRESS_TRACKING_ID', 'default')

# Optimisation des regex
COIN_LINK_REGEX = re.compile(
    r'https?:\/\/(?:[a-z]+\.)?aliexpress\.com\/p\/coin-index\/index\.html\?.*productIds=([\d,]+)',
    re.IGNORECASE
)

class CoinLinkProcessor:
    @staticmethod
    async def extract_main_product(coin_url: str) -> dict:
        """Extrait le produit principal de la page Coin"""
        match = COIN_LINK_REGEX.search(coin_url)
        if not match:
            return None
            
        product_ids = match.group(1).split(',')
        if not product_ids:
            return None
            
        main_product_id = product_ids[0]  # Premier produit = produit principal
        
        # Récupération des infos produit
        product_data = await ProductFetcher.fetch_product(main_product_id)
        if not product_data:
            return None
            
        # Génération des liens
        coin_link = await LinkGenerator.generate_coin_link(coin_url)
        product_link = await LinkGenerator.generate_product_link(main_product_id)
        
        return {
            'id': main_product_id,
            'title': product_data.get('title', f'Produit {main_product_id}'),
            'price': product_data.get('price'),
            'currency': product_data.get('currency', 'USD'),
            'image': product_data.get('image_url'),
            'coin_link': coin_link,
            'product_link': product_link
        }

class ProductFetcher:
    @staticmethod
    async def fetch_product(product_id: str) -> dict:
        """Récupère les infos d'un produit"""
        # Implémentation existante de fetch_product_details_v2
        # ... (votre code existant) ...

class LinkGenerator:
    @staticmethod
    async def generate_coin_link(coin_url: str) -> str:
        """Génère un lien Coin avec tracking"""
        parsed = urlparse(coin_url)
        query = dict(parse_qsl(parsed.query))
        
        query.update({
            'aff_platform': 'api-new-link-generate',
            'aff_trace_key': ALIEXPRESS_TRACKING_ID,
            'terminal_id': str(int(time.time()))
        })
        
        return urlunparse((
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            urlencode(query),
            parsed.fragment
        ))

    @staticmethod
    async def generate_product_link(product_id: str) -> str:
        """Génère un lien produit standard avec tracking"""
        base_url = f"https://www.aliexpress.com/item/{product_id}.html"
        links = await generate_affiliate_links_batch([base_url])
        return links.get(base_url, base_url)

async def handle_coin_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    coin_url = update.message.text
    chat_id = update.effective_chat.id
    
    product_info = await CoinLinkProcessor.extract_main_product(coin_url)
    if not product_info:
        await update.message.reply_text("❌ Impossible de traiter ce lien Coin")
        return
    
    # Construction du message
    message = [
        f"🌟 <b>PRODUIT PRINCIPAL</b> 🌟",
        f"\n📌 <b>{product_info['title']}</b>",
        f"\n💰 <b>Prix: {product_info['price']} {product_info['currency']}</b>",
        f"\n🪙 <b>Lien Coin Offer:</b> {product_info['coin_link']}",
        f"\n🛒 <b>Lien Standard:</b> {product_info['product_link']}",
        f"\n\n💡 Ce produit apparaît en tête de la page Coin"
    ]
    
    # Boutons d'action
    keyboard = [
        [InlineKeyboardButton("🛒 Acheter avec Coins", url=product_info['coin_link'])],
        [InlineKeyboardButton("📢 Voir tous les produits", url=coin_url)]
    ]
    
    # Envoi du message
    if product_info['image']:
        await context.bot.send_photo(
            chat_id=chat_id,
            photo=product_info['image'],
            caption="\n".join(message),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await context.bot.send_message(
            chat_id=chat_id,
            text="\n".join(message),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

# ... (le reste de votre implémentation existante) ...

def main():
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Handler spécifique pour les liens Coin
    application.add_handler(MessageHandler(
        filters.TEXT & filters.Regex(COIN_LINK_REGEX),
        handle_coin_link
    ))
    
    # ... (autres handlers) ...
    
    application.run_polling()

if __name__ == "__main__":
    main()
