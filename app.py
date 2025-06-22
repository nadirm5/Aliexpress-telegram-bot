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

# Configuration
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
ALIEXPRESS_APP_KEY = os.getenv('ALIEXPRESS_APP_KEY')
ALIEXPRESS_APP_SECRET = os.getenv('ALIEXPRESS_APP_SECRET')
TARGET_CURRENCY = os.getenv('TARGET_CURRENCY', '')
TARGET_LANGUAGE = os.getenv('TARGET_LANGUAGE', 'en')
QUERY_COUNTRY = os.getenv('QUERY_COUNTRY', 'US')
ALIEXPRESS_TRACKING_ID = os.getenv('ALIEXPRESS_TRACKING_ID', 'default')
ALIEXPRESS_API_URL = 'https://api-sg.aliexpress.com/sync'
QUERY_FIELDS = 'product_main_image_url,target_sale_price,product_title,target_sale_price_currency,shop_url,shop_name,shop_rating'
CACHE_EXPIRY_DAYS = 1
CACHE_EXPIRY_SECONDS = CACHE_EXPIRY_DAYS * 24 * 60 * 60
MAX_WORKERS = 5  # Réduit pour Render gratuit

# Conversion devise (statique)
USD_TO_DZD = 255  # Taux fixe

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Regex pour tous les liens AliExpress
ALIEXPRESS_URL_REGEX = re.compile(
    r'https?://(?:[a-z]+\.)?aliexpress\.(?:com|ru|es|fr|pt|it|pl|nl|co\.kr|co\.jp|com\.br|com\.tr|com\.vn|us|id|th|ar)(?:\.[\w-]+)?/[^\s<>"]*',
    re.IGNORECASE
)

PRODUCT_ID_REGEX = re.compile(r'/item/(\d+)\.html', re.IGNORECASE)

class AliExpressBot:
    def __init__(self):
        self.client = iop.IopClient(ALIEXPRESS_API_URL, ALIEXPRESS_APP_KEY, ALIEXPRESS_APP_SECRET)
        self.executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)
        self.session = aiohttp.ClientSession()
        
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_html(
            "👋 مرحبًا بك في بوت خصومات علي إكسبريس! 🛍️\n\n"
            "🔍 <b>كيفية الاستخدام:</b>\n"
            "1️⃣ انسخ رابط منتج أو صفحة من علي إكسبريس 📋\n"
            "2️⃣ أرسل الرابط هنا 📤\n"
            "3️⃣ ستحصل على روابط باقل الاسعار ✨\n\n"
            "🔗 يدعم جميع أنواع الروابط (منتجات، عروض، فئات)\n"
            "🚀 أرسل رابطًا للبدء! 🎁"
        )

    async def generate_affiliate_link(self, url: str) -> str:
        try:
            request = iop.IopRequest('aliexpress.affiliate.link.generate')
            request.add_api_param('promotion_link_type', '0')
            request.add_api_param('source_values', url)
            request.add_api_param('tracking_id', ALIEXPRESS_TRACKING_ID)
            
            response = await asyncio.get_event_loop().run_in_executor(
                self.executor, self.client.execute, request
            )
            
            if response and response.body:
                data = json.loads(response.body) if isinstance(response.body, str) else response.body
                return data['aliexpress_affiliate_link_generate_response']['resp_result']['result']['promotion_links']['promotion_link'][0]['promotion_link']
        except Exception as e:
            logger.error(f"Error generating link: {e}")
        return url

    async def get_product_details(self, product_id: str) -> dict:
        try:
            request = iop.IopRequest('aliexpress.affiliate.productdetail.get')
            request.add_api_param('fields', QUERY_FIELDS)
            request.add_api_param('product_ids', product_id)
            request.add_api_param('tracking_id', ALIEXPRESS_TRACKING_ID)
            
            response = await asyncio.get_event_loop().run_in_executor(
                self.executor, self.client.execute, request
            )
            
            if response and response.body:
                data = json.loads(response.body) if isinstance(response.body, str) else response.body
                product = data['aliexpress_affiliate_productdetail_get_response']['resp_result']['result']['products']['product'][0]
                return {
                    'title': product.get('product_title'),
                    'price': product.get('target_sale_price'),
                    'currency': product.get('target_sale_price_currency'),
                    'image': product.get('product_main_image_url'),
                    'store': product.get('shop_name'),
                    'rating': product.get('shop_rating')
                }
        except Exception as e:
            logger.error(f"Error fetching product {product_id}: {e}")
        return None

    def build_reply_markup(self):
        keyboard = [
            [InlineKeyboardButton("🎫 Coupons", url="https://s.click.aliexpress.com/e/_oliYXEJ")],
            [InlineKeyboardButton("📢 Channel", url="https://t.me/RayanCoupon")]
        ]
        return InlineKeyboardMarkup(keyboard)

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message or not update.message.text:
            return

        message_text = update.message.text
        chat_id = update.effective_chat.id
        
        urls = re.findall(ALIEXPRESS_URL_REGEX, message_text)
        if not urls:
            await update.message.reply_text("❌ لم يتم العثور على رابط AliExpress في الرسالة")
            return

        processing_msg = await update.message.reply_text("⏳ جاري معالجة الرابط...")
        
        try:
            results = []
            for url in urls[:3]:  # Limite à 3 URLs pour Render gratuit
                product_id = extract_product_id(url)
                if product_id:
                    # Traitement produit
                    product_data = await self.get_product_details(product_id)
                    affiliate_link = await self.generate_affiliate_link(url)
                    
                    if product_data:
                        response = [
                            f"✨ {product_data['title']}",
                            f"\n💰 السعر: ${product_data['price']} | 🇩🇿 {int(float(product_data['price']) * USD_TO_DZD} DA",
                            f"\n🪙 رابط التخفيض: {affiliate_link}",
                            f"\n🏪 المتجر: {product_data['store']} ({product_data['rating']}%)",
                            "\n🚀────────🚀",
                            "🔥 احصل على أفضل سعر باستخدام البوت 👇",
                            "🤖 @Rayanaliexpress_bot"
                        ]
                        results.append("\n".join(response))
                else:
                    # Traitement page spéciale
                    affiliate_link = await self.generate_affiliate_link(url)
                    results.append(f"📌 رابط الصفحة الخاصة:\n{affiliate_link}")

            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=processing_msg.message_id,
                text="\n\n".join(results),
                reply_markup=self.build_reply_markup(),
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            logger.error(f"Error: {e}")
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=processing_msg.message_id,
                text="❌ حدث خطأ أثناء معالجة الرابط"
            )

def extract_product_id(url: str) -> str | None:
    match = PRODUCT_ID_REGEX.search(url)
    return match.group(1) if match else None

def main():
    bot = AliExpressBot()
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", bot.start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_message))
    
    logger.info("Bot démarré...")
    app.run_polling()

if __name__ == "__main__":
    main()
