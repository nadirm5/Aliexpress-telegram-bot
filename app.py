import os
import re
import logging
import aiohttp
import asyncio
from datetime import datetime
from urllib.parse import urlparse, urlencode, parse_qsl
from typing import Dict, List, Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode

# Configuration
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Load environment variables
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
ALI_API_KEY = os.getenv('ALIEXPRESS_API_KEY')
TRACKING_ID = os.getenv('ALIEXPRESS_TRACKING_ID')

class AliExpressProBot:
    def __init__(self):
        self.session = aiohttp.ClientSession()
        self.offer_types = {
            'coin': {
                'name': "تخفيض العملات",
                'emoji': "🪙",
                'params': {'sourceType': '620', 'aff_platform': 'api-new-link-generate'}
            },
            'superdeals': {
                'name': "سوبر ديلز",
                'emoji': "🛒",
                'params': {'sourceType': '570', 'scm': '1007.41618.435122.0'}
            },
            'bundle': {
                'name': "عروض مجمعة",
                'emoji': "📦",
                'params': {'scm': '1007.41618.435122.0', 'pvid': '1d6d5bee-18fd-4156-9306-d2d9325a2591'}
            }
        }

    async def extract_product_id(self, url: str) -> Optional[str]:
        """Extract product ID from any AliExpress URL"""
        patterns = [
            r'/item/(\d+)\.html',
            r'/product/(\d+)',
            r'/(\d+)/.*\.html',
            r'id=(\d+)',
            r'productIds=(\d+)'
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None

    async def generate_affiliate_link(self, base_url: str, offer_type: str = None) -> str:
        """Generate tracked affiliate link with offer parameters"""
        parsed = urlparse(base_url)
        query = dict(parse_qsl(parsed.query))
        
        if offer_type in self.offer_types:
            query.update(self.offer_types[offer_type]['params'])
        
        query.update({
            'aff_trace_key': TRACKING_ID,
            'terminal_id': str(int(datetime.now().timestamp()))
        })
        
        return urlunparse((
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            urlencode(query),
            parsed.fragment
        ))

    async def fetch_product_data(self, product_id: str) -> Dict:
        """Fetch detailed product information from AliExpress API"""
        try:
            async with self.session.get(
                "https://api.aliababa.com/aliexpress/item/get",
                params={
                    'itemId': product_id,
                    'api_key': ALI_API_KEY
                }
            ) as response:
                data = await response.json()
                
                if not data.get('success'):
                    logger.error(f"API Error: {data.get('message')}")
                    return None
                
                item = data['result']['item']
                store = data['result']['store']
                
                return {
                    'title': item.get('title'),
                    'image_url': item.get('imageUrl'),
                    'original_price': item['price']['originalPrice'],
                    'current_price': item['price']['salePrice'],
                    'currency': item['price']['currency'],
                    'discount': item['price']['discount'],
                    'store_name': store.get('storeName'),
                    'store_rating': store.get('ratingScore'),
                    'shipping': item['shipping']['companyName'],
                    'shipping_fee': item['shipping']['freight']
                }
        except Exception as e:
            logger.error(f"Fetch Error: {str(e)}")
            return None

    async def create_response(self, product: Dict, links: Dict) -> Dict:
        """Create complete response message with buttons"""
        # Format prices
        original_price = f"{product['original_price']} {product['currency']}"
        current_price = f"{product['current_price']} {product['currency']}"
        shipping_fee = f"{product['shipping_fee']} {product['currency']}" if product['shipping_fee'] else "مجانا"
        
        # Create message text
        message = [
            f"🌟 <b>{product['title']}</b> 🌟",
            f"\n🏪 <b>المتجر:</b> {product['store_name']}",
            f"⭐ <b>تقييم المتجر:</b> {product['store_rating']}%",
            f"\n💰 <b>السعر الأصلي:</b> <s>{original_price}</s>",
            f"🪙 <b>السعر بعد التخفيض:</b> <b>{current_price}</b>",
            f"📉 <b>نسبة التخفيض:</b> {product['discount']}%",
            f"\n🚚 <b>الشحن:</b> {product['shipping']} ({shipping_fee})"
        ]
        
        # Add offers section
        message.append("\n\n🎁 <b>العروض المتاحة:</b>")
        for offer_type, details in self.offer_types.items():
            if offer_type in links:
                message.append(f"\n{details['emoji']} <b>{details['name']}:</b> {links[offer_type]}")
        
        # Create inline keyboard
        keyboard = [
            [InlineKeyboardButton("🛒 شراء بالعملات", url=links['coin'])],
            [
                InlineKeyboardButton("📦 عروض مجمعة", url=links['bundle']),
                InlineKeyboardButton("⚡ سوبر ديلز", url=links['superdeals'])
            ],
            [InlineKeyboardButton("📢 قناتنا", url="https://t.me/yourchannel")]
        ]
        
        return {
            'text': "\n".join(message),
            'image': product['image_url'],
            'buttons': InlineKeyboardMarkup(keyboard)
        }

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Main message handler"""
        url = update.message.text
        product_id = await self.extract_product_id(url)
        
        if not product_id:
            await update.message.reply_text("⚠️ الرابط غير صحيح. يرجى إرسال رابط منتج AliExpress صحيح.")
            return
            
        await update.message.reply_chat_action(action='typing')
        
        product = await self.fetch_product_data(product_id)
        if not product:
            await update.message.reply_text("❌ تعذر جلب معلومات المنتج. يرجى المحاولة لاحقاً.")
            return
            
        base_url = f"https://www.aliexpress.com/item/{product_id}.html"
        links = {
            'standard': await self.generate_affiliate_link(base_url),
            'coin': await self.generate_affiliate_link(base_url, 'coin'),
            'superdeals': await self.generate_affiliate_link(base_url, 'superdeals'),
            'bundle': await self.generate_affiliate_link(base_url, 'bundle')
        }
        
        response = await self.create_response(product, links)
        
        try:
            if response['image']:
                await update.message.reply_photo(
                    photo=response['image'],
                    caption=response['text'],
                    parse_mode=ParseMode.HTML,
                    reply_markup=response['buttons']
                )
            else:
                await update.message.reply_text(
                    text=response['text'],
                    parse_mode=ParseMode.HTML,
                    reply_markup=response['buttons']
                )
        except Exception as e:
            logger.error(f"Send Error: {str(e)}")
            await update.message.reply_text(
                text=response['text'],
                parse_mode=ParseMode.HTML
            )

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start command handler"""
        welcome = (
            "مرحباً بكم في بوت AliExpress المحترف!\n\n"
            "📌 أرسل لي أي رابط منتج من AliExpress وسأوفر لك:\n"
            "- أفضل الأسعار مع التخفيضات\n"
            "- روابط متابعة آمنة\n"
            "- معلومات شاملة عن المنتج\n"
            "- عروض خاصة بالعملات والعروض المجمعة\n\n"
            "🚀 ابدأ الآن بإرسال رابط المنتج!"
        )
        await update.message.reply_text(welcome)

async def main():
    bot = AliExpressProBot()
    application = Application.builder().token(TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", bot.start))
    application.add_handler(MessageHandler(
        filters.TEXT & filters.Regex(r'aliexpress\.com'),
        bot.handle_message
    ))
    
    # Start the bot
    await application.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
