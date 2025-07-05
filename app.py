import os
import re
import json
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode
import aiohttp
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')

async def extract_coin_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Détection des liens Coin
    if not update.message.text or 'coin-index' not in update.message.text:
        return
    
    coin_url = update.message.text
    product_ids = re.findall(r'productIds=([\d,]+)', coin_url)
    
    if not product_ids:
        await update.message.reply_text("❌ Aucun ID de produit trouvé dans le lien")
        return
    
    products = []
    async with aiohttp.ClientSession() as session:
        for pid in product_ids[0].split(','):
            # Scraping direct de la page Coin
            url = f"https://m.aliexpress.com/api/products/{pid}/coin-info"
            try:
                async with session.get(url) as resp:
                    data = await resp.json()
                    if data.get('success'):
                        products.append({
                            'title': data['data']['title'],
                            'price': data['data']['price'],
                            'coin_price': data['data']['coinPrice'],
                            'url': f"https://fr.aliexpress.com/item/{pid}.html"
                        })
            except Exception as e:
                print(f"Erreur pour {pid}: {e}")
    
    if not products:
        await update.message.reply_text("⚠️ Aucun prix avec coins trouvé")
        return
    
    # Envoi des résultats
    for p in products[:3]:  # Limite à 3 produits
        await update.message.reply_text(
            f"🪙 <b>{p['title']}</b>\n"
            f"💰 Prix: {p['price']} → <b>{p['coin_price']} avec coins</b>\n"
            f"🔗 <a href='{p['url']}'>Voir l'offre</a>",
            parse_mode=ParseMode.HTML
        )

app = Application.builder().token(TOKEN).build()
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, extract_coin_products))
app.run_polling()
