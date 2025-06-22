import os
import re
import aiohttp
from urllib.parse import urlparse, urlencode
from telegram import Update, Bot
from telegram.ext import Application, MessageHandler, filters

# Configuration
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TRACKING_ID = "votre_tracking_id"  # Remplacez par votre vrai tracking ID

async def handle_message(update: Update, context):
    url = update.message.text
    
    # Extraire l'ID du produit
    product_id = re.search(r'productIds=(\d+)', url)
    if not product_id:
        await update.message.reply_text("❌ Lien Coin non valide")
        return
    
    product_id = product_id.group(1)
    
    # Générer le lien Coin avec tracking
    coin_link = f"https://www.aliexpress.com/item/{product_id}.html"
    affiliate_link = await generate_affiliate_link(coin_link)
    
    # Réponse simple avec le lien
    await update.message.reply_text(
        f"🪙 Produit principal de la page Coin:\n\n"
        f"{affiliate_link}",
        disable_web_page_preview=True
    )

async def generate_affiliate_link(url):
    """Ajoute le tracking ID au lien"""
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query))
    query.update({
        'aff_platform': 'api-new-link-generate',
        'aff_trace_key': TRACKING_ID
    })
    return urlunparse((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        parsed.params,
        urlencode(query),
        parsed.fragment
    ))

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()

if __name__ == '__main__':
    main()
