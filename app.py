#!/usr/bin/env python
import os
import re
import json
import urllib.parse
from urllib.parse import urlparse, parse_qs
from threading import Thread
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackContext, filters
from aliexpress_api import AliexpressApi, models
from dotenv import load_dotenv

# Configuration initiale
load_dotenv()
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
ALI_KEY = os.getenv('ALIEXPRESS_APP_KEY')
ALI_SECRET = os.getenv('ALIEXPRESS_APP_SECRET')
TRACKING_ID = os.getenv('ALIEXPRESS_TRACKING_ID', 'default')

# Initialisation des APIs
aliexpress = AliexpressApi(ALI_KEY, ALI_SECRET, models.Language.EN, models.Currency.EUR, TRACKING_ID)
bot = Application.builder().token(TOKEN).build()

# Serveur web pour Render
app = Flask(__name__)
@app.route('/')
def home(): return "Bot AliExpress en ligne"

def run_flask():
    app.run(host='0.0.0.0', port=8080)

Thread(target=run_flask, daemon=True).start()

# Claviers Inline
def create_keyboard():
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("⭐️ ألعاب العملات ⭐️", callback_data="games")],
        [InlineKeyboardButton("🛒 تخفيض السلة", callback_data="cart")],
        [InlineKeyboardButton("📺 القناة", url="https://t.me/AliXPromotion")]
    ])
    return keyboard

# Handlers
async def start(update: Update, context: CallbackContext):
    await update.message.reply_text(
        "مرحبا بك! أرسل رابط منتج AliExpress للحصول على أفضل سعر 👇",
        reply_markup=create_keyboard()
    )

async def handle_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    if query.data == "games":
        await query.message.reply_text("🎮 ألعاب جمع العملات:")
        # ... (votre logique pour les jeux)
    elif query.data == "cart":
        await query.message.reply_text("🛒 كيفية استخدام تخفيض السلة...")

async def handle_message(update: Update, context: CallbackContext):
    text = update.message.text
    if not text: return
    
    # Extraction du lien
    link = re.search(r'https?://[^\s]+', text)
    if not link or "aliexpress" not in link.group(0).lower():
        await update.message.reply_text("⚠️ الرابط غير صحيح! أرسل رابط AliExpress فقط")
        return
    
    try:
        # Récupération des infos produit
        product = aliexpress.get_products_details([link.group(0)])[0]
        aff_links = aliexpress.get_affiliate_links(link.group(0))
        
        # Préparation du message
        msg = f"""
🛍 {product.product_title}
💰 السعر: {product.target.sale_price} €
🔗 روابط التخفيض:
1. {aff_links[0].promotion_link}
2. {aff_links[1].promotion_link if len(aff_links) > 1 else 'N/A'}
        """
        
        # Envoi avec image si disponible
        if hasattr(product, 'product_main_image_url'):
            await update.message.reply_photo(
                photo=product.product_main_image_url,
                caption=msg,
                reply_markup=create_keyboard()
            )
        else:
            await update.message.reply_text(msg, reply_markup=create_keyboard())
            
    except Exception as e:
        await update.message.reply_text("❌ حدث خطأ أثناء المعالجة، حاول لاحقاً")

# Configuration des handlers
bot.add_handler(CommandHandler("start", start))
bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
bot.add_handler(CallbackQueryHandler(handle_callback))

if __name__ == "__main__":
    print("Démarrage du bot...")
    bot.run_polling()
