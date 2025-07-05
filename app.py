import logging
import os
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode, ChatAction
import iop
from dotenv import load_dotenv

load_dotenv()

# Configuration
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
ALIEXPRESS_APP_KEY = os.getenv('ALIEXPRESS_APP_KEY')
ALIEXPRESS_APP_SECRET = os.getenv('ALIEXPRESS_APP_SECRET')

# Initialisation API
aliexpress_client = iop.IopClient('https://api-sg.aliexpress.com/sync', 
                                ALIEXPRESS_APP_KEY, 
                                ALIEXPRESS_APP_SECRET)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def search_exact_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = ' '.join(context.args)
    if not query:
        await update.message.reply_text("❌ Veuillez entrer le nom COMPLET du produit")
        return

    await update.message.reply_chat_action(ChatAction.TYPING)

    try:
        # 1. Recherche ultra-précise
        request = iop.IopRequest('aliexpress.affiliate.product.query')
        request.add_api_param('keywords', f'"{query}"')  # Guillemets pour recherche exacte
        request.add_api_param('fields', 'product_title,product_main_image_url,target_sale_price,product_id')
        request.add_api_param('page_size', '3')  # Top 3 résultats les plus pertinents
        request.add_api_param('sort', 'relevant')

        response = await asyncio.to_thread(aliexpress_client.execute, request)

        if not response or not response.body:
            await update.message.reply_text(f"⚠️ Aucun résultat trouvé pour '{query}'")
            return

        data = json.loads(response.body) if isinstance(response.body, str) else response.body
        products = data.get('aliexpress_affiliate_product_query_response', {}).get('resp_result', {}).get('result', {}).get('products', {}).get('product', [])

        if not products:
            await update.message.reply_text(f"❌ Produit introuvable. Essayez avec:\n- La référence exacte\n- Le modèle complet\n- La marque + spécifications")
            return

        # 2. Vérification de la pertinence
        exact_matches = [p for p in products if query.lower() in p.get('product_title', '').lower()]
        
        if not exact_matches:
            await update.message.reply_text(f"ℹ️ Résultats similaires (le produit exact n'existe peut-être pas):")
            products = products[:3]  # Limite à 3 résultats génériques
        else:
            await update.message.reply_text("✅ Produit exact trouvé:")
            products = exact_matches[:3]  # Limite à 3 résultats exacts

        # 3. Affichage des résultats
        for product in products:
            title = product.get('product_title', 'Sans titre')
            price = product.get('target_sale_price', 'N/A')
            image_url = product.get('product_main_image_url')
            product_url = f"https://www.aliexpress.com/item/{product.get('product_id')}"

            message = (
                f"📌 <b>{title}</b>\n"
                f"💰 <b>Prix: {price}</b>\n"
                f"🔗 <a href='{product_url}'>Voir sur AliExpress</a>"
            )

            if image_url:
                await update.message.reply_photo(photo=image_url, caption=message, parse_mode=ParseMode.HTML)
            else:
                await update.message.reply_text(message, parse_mode=ParseMode.HTML)

    except Exception as e:
        logger.error(f"Erreur: {e}")
        await update.message.reply_text("⚠️ Erreur technique. Réessayez avec une recherche plus précise.")

def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("search", search_exact_product))
    app.run_polling()

if __name__ == "__main__":
    main()
