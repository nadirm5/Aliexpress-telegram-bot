import logging
import os
import re
import asyncio
from urllib.parse import urlparse, urlencode
from dotenv import load_dotenv
import aiohttp
from typing import Dict, List

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode

# Configuration
load_dotenv()
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
ALI_API_KEY = os.getenv('ALIEXPRESS_API_KEY')
TRACKING_ID = os.getenv('ALIEXPRESS_TRACKING_ID')

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class AliExpressBot:
    def __init__(self):
        self.session = aiohttp.ClientSession()
        self.OFFER_TYPES = {
            'coin': {
                'name': "تخفيض العملات",
                'emoji': "🪙",
                'params': {'sourceType': '620'}
            },
            'superdeals': {
                'name': "سوبر ديلز",
                'emoji': "🛒", 
                'params': {'sourceType': '570'}
            },
            'bundle': {
                'name': "عروض مجمعة",
                'emoji': "📦",
                'params': {'scm': '1007.41618.435122.0'}
            }
        }

    async def extract_product_id(self, url: str) -> str:
        """Extract product ID from any AliExpress URL"""
        patterns = [
            r'/item/(\d+)\.html',
            r'/product/(\d+)',
            r'/(\d+)/.*\.html',
            r'id=(\d+)'
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None

    async def generate_affiliate_link(self, base_url: str, offer_type: str = None) -> str:
        """Generate tracked affiliate link with optional offer parameters"""
        parsed = urlparse(base_url)
        query = dict(parse_qsl(parsed.query))
        
        if offer_type and offer_type in self.OFFER_TYPES:
            query.update(self.OFFER_TYPES[offer_type]['params'])
        
        query.update({
            'aff_platform': 'api-new-link-generate',
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

    async def get_product_data(self, product_id: str) -> Dict:
        """Fetch product details from AliExpress API"""
        try:
            async with self.session.get(
                f"https://api.aliexpress.com/item/{product_id}",
                params={'api_key': ALI_API_KEY}
            ) as response:
                data = await response.json()
                return {
                    'title': data.get('title', 'Unknown Product'),
                    'original_price': data.get('price', {}).get('original', 'N/A'),
                    'current_price': data.get('price', {}).get('current', 'N/A'),
                    'currency': data.get('price', {}).get('currency', 'USD'),
                    'store_name': data.get('store', {}).get('name', 'Unknown Store'),
                    'store_rating': data.get('store', {}).get('rating', 0),
                    'image_url': data.get('image_url')
                }
        except Exception as e:
            logger.error(f"API Error: {e}")
            return None

    async def calculate_discount(self, original: float, current: float) -> int:
        """Calculate discount percentage"""
        try:
            return int(((original - current) / original) * 100)
        except:
            return 0

    async def create_offer_message(self, product: Dict, links: Dict) -> str:
        """Generate formatted message with all offers"""
        message = [
            f"✨ <b>{product['title']}</b> ✨",
            f"\n🏪 المتجر: <b>{product['store_name']}</b>",
            f"⭐ التقييم: <b>{product['store_rating']}%</b>",
            f"\n💰 السعر الأصلي: <b>{product['original_price']} {product['currency']}</b>"
        ]
        
        for offer_type, details in self.OFFER_TYPES.items():
            if offer_type in links:
                message.extend([
                    f"\n{details['emoji']} <b>{details['name']}:</b>",
                    f"💲 <b>{product['current_price']} {product['currency']}</b>",
                    f"🔗 {links[offer_type]}"
                ])
        
        if 'coin' in links:
            discount = await self.calculate_discount(
                float(product['original_price'].replace('$', '')), 
                float(product['current_price'].replace('$', ''))
            )
            message.append(f"\n🛍 نسبة التخفيض: <b>{discount}%</b>")
        
        return "\n".join(message)

    async def handle_product_link(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        url = update.message.text
        product_id = await self.extract_product_id(url)
        
        if not product_id:
            await update.message.reply_text("❌ لم يتم العثور على معرف المنتج في الرابط")
            return
            
        product = await self.get_product_data(product_id)
        if not product:
            await update.message.reply_text("❌ تعذر جلب بيانات المنتج")
            return
            
        # Generate all offer links
        base_url = f"https://www.aliexpress.com/item/{product_id}.html"
        links = {
            'standard': await self.generate_affiliate_link(base_url),
            'coin': await self.generate_affiliate_link(base_url, 'coin'),
            'superdeals': await self.generate_affiliate_link(base_url, 'superdeals'),
            'bundle': await self.generate_affiliate_link(base_url, 'bundle')
        }
        
        # Create and send message
        message = await self.create_offer_message(product, links)
        keyboard = [
            [InlineKeyboardButton("🛒 اشتر الآن", url=links['coin'])],
            [InlineKeyboardButton("📢 جميع العروض", url=links['standard'])]
        ]
        
        if product.get('image_url'):
            await update.message.reply_photo(
                photo=product['image_url'],
                caption=message,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            await update.message.reply_text(
                text=message,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

def main():
    bot = AliExpressBot()
    application = Application.builder().token(TOKEN).build()
    
    application.add_handler(MessageHandler(
        filters.TEXT & filters.Regex(r'aliexpress\.com'),
        bot.handle_product_link
    ))
    
    application.run_polling()

if __name__ == "__main__":
    main()
