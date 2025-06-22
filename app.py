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

# Configuration (gardez votre configuration existante)
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
ALIEXPRESS_APP_KEY = os.getenv('ALIEXPRESS_APP_KEY')
ALIEXPRESS_APP_SECRET = os.getenv('ALIEXPRESS_APP_SECRET')
TARGET_CURRENCY = os.getenv('TARGET_CURRENCY', '')
TARGET_LANGUAGE = os.getenv('TARGET_LANGUAGE', 'en')
QUERY_COUNTRY = os.getenv('QUERY_COUNTRY', 'US')
ALIEXPRESS_TRACKING_ID = os.getenv('ALIEXPRESS_TRACKING_ID', 'default')
ALIEXPRESS_API_URL = 'https://api-sg.aliexpress.com/sync'
QUERY_FIELDS = 'product_main_image_url,target_sale_price,product_title,target_sale_price_currency'
CACHE_EXPIRY_DAYS = 1
CACHE_EXPIRY_SECONDS = CACHE_EXPIRY_DAYS * 24 * 60 * 60
MAX_WORKERS = 10

# Setup logging (gardez votre configuration existante)
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Initialisation du client AliExpress (gardez votre configuration existante)
try:
    aliexpress_client = iop.IopClient(ALIEXPRESS_API_URL, ALIEXPRESS_APP_KEY, ALIEXPRESS_APP_SECRET)
    logger.info("AliExpress API client initialized.")
except Exception as e:
    logger.exception(f"Error initializing AliExpress API client: {e}")
    exit()

executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)

# Nouvelle regex pour capturer TOUS les liens AliExpress
ALIEXPRESS_URL_REGEX = re.compile(
    r'https?://(?:[a-z]+\.)?aliexpress\.(?:com|ru|es|fr|pt|it|pl|nl|co\.kr|co\.jp|com\.br|com\.tr|com\.vn|us|id|th|ar)(?:\.[\w-]+)?/[^\s<>"]*',
    re.IGNORECASE
)

# Fonction pour extraire tous les liens AliExpress d'un texte
def extract_all_aliexpress_urls(text: str) -> list[str]:
    return ALIEXPRESS_URL_REGEX.findall(text)

# Fonction pour générer un lien d'affiliation pour n'importe quelle URL AliExpress
async def generate_affiliate_link(url: str) -> str:
    try:
        # Si ce n'est pas déjà un lien d'affiliation, on le convertit
        if not url.startswith(('https://s.click.aliexpress.com', 'https://a.aliexpress.com')):
            request = iop.IopRequest('aliexpress.affiliate.link.generate')
            request.add_api_param('promotion_link_type', '0')
            request.add_api_param('source_values', url)
            request.add_api_param('tracking_id', ALIEXPRESS_TRACKING_ID)
            
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(executor, aliexpress_client.execute, request)
            
            if response and response.body:
                response_data = json.loads(response.body) if isinstance(response.body, str) else response.body
                if 'aliexpress_affiliate_link_generate_response' in response_data:
                    result = response_data['aliexpress_affiliate_link_generate_response']['resp_result']['result']
                    return result['promotion_links']['promotion_link'][0]['promotion_link']
        
        return url  # Retourne l'URL originale si la conversion échoue
    except Exception as e:
        logger.error(f"Error generating affiliate link: {e}")
        return url

# Handler pour tous les messages
async def handle_all_messages(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return

    message_text = update.message.text
    chat_id = update.effective_chat.id
    
    # Trouver tous les liens AliExpress dans le message
    aliexpress_urls = extract_all_aliexpress_urls(message_text)
    
    if not aliexpress_urls:
        await update.message.reply_text("Je ne trouve pas de lien AliExpress dans votre message.")
        return
    
    # Envoyer un message indiquant que le traitement est en cours
    processing_msg = await update.message.reply_text("🔄 Traitement de votre lien AliExpress...")
    
    # Générer les liens d'affiliation pour chaque URL trouvée
    results = []
    for url in aliexpress_urls:
        affiliate_link = await generate_affiliate_link(url)
        results.append(f"🔗 Lien d'affiliation: {affiliate_link}")
    
    # Répondre avec tous les liens générés
    response_text = "\n\n".join(results)
    await context.bot.edit_message_text(
        chat_id=chat_id,
        message_id=processing_msg.message_id,
        text=response_text,
        disable_web_page_preview=True
    )

# Fonction principale
def main() -> None:
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Commandes
    application.add_handler(CommandHandler("start", start))
    
    # Handler pour tous les messages texte contenant des liens AliExpress
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.Regex(ALIEXPRESS_URL_REGEX),
        handle_all_messages
    ))
    
    # Handler pour les autres messages
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        lambda update, context: update.message.reply_text("Envoyez-moi un lien AliExpress et je vous donnerai le lien d'affiliation !")
    ))
    
    logger.info("Bot démarré et en écoute...")
    application.run_polling()

if __name__ == "__main__":
    main()
