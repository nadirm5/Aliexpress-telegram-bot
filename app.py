import os
import re
import aiohttp
from urllib.parse import urlparse, urlencode
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, MessageHandler, filters, ContextTypes

# Configuration
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN') or "VOTRE_TOKEN_BOT"
TRACKING_ID = os.getenv('ALI_TRACKING_ID') or "votre_tracking_id"

class AliExpressBot:
    def __init__(self):
        self.session = aiohttp.ClientSession()
    
    async def extract_product_id(self, url: str) -> str:
        """Extrait l'ID produit de n'importe quel lien AliExpress"""
        # Détection des liens Coin
        coin_match = re.search(r'productIds=([\d,]+)', url)
        if coin_match:
            return coin_match.group(1).split(',')[0]  # Premier produit
        
        # Détection standard
        patterns = [
            r'/item/(\d+)\.html',
            r'/(\d+)/.*\.html',
            r'id=(\d+)'
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None

    async def generate_affiliate_link(self, product_id: str, offer_type: str = None) -> str:
        """Génère un lien affilié avec tracking"""
        base_url = f"https://www.aliexpress.com/item/{product_id}.html"
        params = {
            'aff_platform': 'api-new-link-generate',
            'aff_trace_key': TRACKING_ID
        }
        
        # Paramètres spécifiques
        if offer_type == "coin":
            params.update({'sourceType': '620', 'channel': 'coin'})
        
        return f"{base_url}?{urlencode(params)}"

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        url = update.message.text
        
        # Extraction de l'ID produit
        product_id = await self.extract_product_id(url)
        if not product_id:
            await update.message.reply_text("❌ Lien AliExpress non valide")
            return
        
        # Génération des liens
        coin_link = await self.generate_affiliate_link(product_id, "coin")
        standard_link = await self.generate_affiliate_link(product_id)
        
        # Réponse avec mise en forme
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🪙 Voir sur Coin Page", url=coin_link)],
            [InlineKeyboardButton("🛒 Acheter Maintenant", url=standard_link)]
        ])
        
        await update.message.reply_text(
            f"🎯 Produit principal trouvé :\n\n"
            f"🔗 Lien Coin (meilleur prix) :\n{coin_link}\n\n"
            f"🔗 Lien Standard :\n{standard_link}",
            reply_markup=keyboard,
            disable_web_page_preview=False
        )

def main():
    bot = AliExpressBot()
    app = Application.builder().token(TOKEN).build()
    
    # Handler pour tous les messages texte contenant 'aliexpress'
    app.add_handler(MessageHandler(
        filters.TEXT & filters.Regex(r'aliexpress\.com'),
        bot.handle_message
    ))
    
    print("🤖 Bot AliExpress en écoute...")
    app.run_polling()

if __name__ == '__main__':
    main()
