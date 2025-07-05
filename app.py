import os
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.constants import ParseMode
import iop
from dotenv import load_dotenv

load_dotenv()

# Configuration minimale
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
APP_KEY = os.getenv('ALIEXPRESS_APP_KEY')
APP_SECRET = os.getenv('ALIEXPRESS_APP_SECRET')

client = iop.IopClient('https://api-sg.aliexpress.com/sync', APP_KEY, APP_SECRET)

async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = ' '.join(context.args)
    
    if not query:
        await update.message.reply_text("❌ Envoyez /search <nom complet du produit>")
        return
    
    try:
        # Requête ultra-précise
        req = iop.IopRequest('aliexpress.affiliate.product.query')
        req.add_api_param('keywords', f'"{query}"')  # Guillemets pour recherche exacte
        req.add_api_param('fields', 'product_title,product_url,target_sale_price')
        req.add_api_param('page_size', '1')  # Seulement le meilleur résultat
        
        result = await client.execute(req)
        product = result.body['aliexpress_affiliate_product_query_response']['resp_result']['result']['products']['product'][0]
        
        await update.message.reply_text(
            f"✅ Produit trouvé :\n\n"
            f"<b>{product['product_title']}</b>\n"
            f"💰 <b>Prix : {product['target_sale_price']}</b>\n"
            f"🔗 <a href='{product['product_url']}'>Acheter maintenant</a>",
            parse_mode=ParseMode.HTML
        )
    
    except Exception:
        await update.message.reply_text(f"⚠️ Aucun résultat exact pour '{query}'\n\n"
                                      "Essayez avec :\n"
                                      "- La référence complète\n"
                                      "- Le modèle exact\n"
                                      "- La marque + spécifications")

app = Application.builder().token(TOKEN).build()
app.add_handler(CommandHandler("search", search))
app.run_polling()
