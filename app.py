import logging
import os
import re
import json
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode, ChatAction
import iop
from dotenv import load_dotenv

load_dotenv()

# Configuration
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
ALIEXPRESS_APP_KEY = os.getenv('ALIEXPRESS_APP_KEY')
ALIEXPRESS_APP_SECRET = os.getenv('ALIEXPRESS_APP_SECRET')
ALIEXPRESS_TRACKING_ID = os.getenv('ALIEXPRESS_TRACKING_ID')

# Initialisation API
aliexpress_client = iop.IopClient('https://api-sg.aliexpress.com/sync', 
                                ALIEXPRESS_APP_KEY, 
                                ALIEXPRESS_APP_SECRET)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_html(
        "🛍️ <b>AliExpress Product Finder</b>\n\n"
        "🔍 <b>Comment utiliser :</b>\n"
        "/search <i>nom_du_produit</i> - Trouve un produit spécifique\n"
        "Ou envoyez un lien AliExpress\n\n"
        "⚡ <i>Obtenez des résultats précis pour vos recherches!</i>"
    )

async def search_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = ' '.join(context.args)
    if not query:
        await update.message.reply_text("❌ Veuillez spécifier un produit")
        return

    await update.message.reply_chat_action(ChatAction.TYPING)

    try:
        # Recherche avec correspondance exacte
        request = iop.IopRequest('aliexpress.affiliate.product.query')
        request.add_api_param('keywords', f'"{query}"')  # Guillemets pour recherche exacte
        request.add_api_param('fields', 'product_title,product_main_image_url,target_sale_price,product_id')
        request.add_api_param('page_size', '1')
        request.add_api_param('sort', 'relevant')

        response = await asyncio.to_thread(aliexpress_client.execute, request)

        if not response or not response.body:
            await update.message.reply_text("⚠️ Aucun résultat trouvé")
            return

        data = json.loads(response.body) if isinstance(response.body, str) else response.body
        products = data.get('aliexpress_affiliate_product_query_response', {}).get('resp_result', {}).get('result', {}).get('products', {}).get('product', [])

        if not products:
            await update.message.reply_text(f"❌ Aucun produit trouvé pour '{query}'")
            return

        product = products[0]
        product_id = product.get('product_id')
        title = product.get('product_title', 'Sans titre')
        price = product.get('target_sale_price', 'N/A')
        image_url = product.get('product_main_image_url')

        # Génération du lien affilié
        product_url = f"https://www.aliexpress.com/item/{product_id}.html"
        affiliate_link = await generate_affiliate_link(product_url)

        message = (
            f"🔍 <b>Résultat exact :</b>\n\n"
            f"📌 <b>{title}</b>\n"
            f"💰 <b>Prix : {price}</b>\n"
            f"🛒 <a href='{affiliate_link}'>Acheter maintenant</a>"
        )

        if image_url:
            await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=image_url,
                caption=message,
                parse_mode=ParseMode.HTML
            )
        else:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=message,
                parse_mode=ParseMode.HTML
            )

    except Exception as e:
        logger.error(f"Erreur de recherche : {e}")
        await update.message.reply_text("⚠️ Une erreur est survenue")

async def generate_affiliate_link(url: str) -> str:
    try:
        request = iop.IopRequest('aliexpress.affiliate.link.generate')
        request.add_api_param('promotion_link_type', '0')
        request.add_api_param('source_values', url)
        request.add_api_param('tracking_id', ALIEXPRESS_TRACKING_ID)
        
        response = await asyncio.to_thread(aliexpress_client.execute, request)
        
        if response and response.body:
            data = json.loads(response.body) if isinstance(response.body, str) else response.body
            return data.get('aliexpress_affiliate_link_generate_response', {}).get('resp_result', {}).get('result', {}).get('promotion_links', {}).get('promotion_link', [{}])[0].get('promotion_link', url)
    except Exception as e:
        logger.error(f"Erreur génération lien : {e}")
    return url

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.text:
        text = update.message.text.strip()
        if text.startswith('/'):
            return
        await search_products(update, context)

def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("search", search_products))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    app.run_polling()

if __name__ == "__main__":
    main()
