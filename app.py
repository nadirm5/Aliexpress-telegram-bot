#!/usr/bin/env python
# coding: utf-8

import os
import re
import json
import urllib.parse
from urllib.parse import urlparse, parse_qs
from flask import Flask
from threading import Thread
import telebot
from telebot import types
from aliexpress_api import AliexpressApi, models
import requests
from dotenv import load_dotenv

# Charger les variables d'environnement
load_dotenv()

# Configuration initiale
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
ALI_APP_KEY = os.getenv('ALIEXPRESS_APP_KEY')
ALI_APP_SECRET = os.getenv('ALIEXPRESS_APP_SECRET')
TRACKING_ID = os.getenv('ALIEXPRESS_TRACKING_ID', 'default')

# Initialiser le bot et l'API AliExpress
bot = telebot.TeleBot(TOKEN)
aliexpress = AliexpressApi(ALI_APP_KEY, ALI_APP_SECRET, 
                          models.Language.EN, 
                          models.Currency.EUR, 
                          TRACKING_ID)

# Créer une application Flask pour Render
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot AliExpress en cours d'exécution"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

# Claviers inline
def create_keyboards():
    keyboard_start = types.InlineKeyboardMarkup(row_width=1)
    btn1 = types.InlineKeyboardButton("⭐️ ألعاب لجمع العملات المعدنية ⭐️", callback_data="games")
    btn2 = types.InlineKeyboardButton("⭐️ تخفيض العملات على منتجات السلة 🛒 ⭐️", callback_data='click')
    btn3 = types.InlineKeyboardButton("❤️ اشترك في القناة للمزيد من العروض ❤️", url="https://t.me/AliXPromotion")
    btn4 = types.InlineKeyboardButton("🎬 شاهد كيفية عمل البوت 🎬", url="https://t.me/AliXPromotion/8")
    btn5 = types.InlineKeyboardButton("💰 حمل تطبيق Aliexpress للحصول على مكافأة 5 دولار 💰", url="https://a.aliexpress.com/_mtV0j3q")
    keyboard_start.add(btn1, btn2, btn3, btn4, btn5)

    keyboard_games = types.InlineKeyboardMarkup(row_width=1)
    games = [
        ("⭐️ صفحة مراجعة وجمع النقاط يوميا ⭐️", "https://s.click.aliexpress.com/e/_on0MwkF"),
        ("⭐️ لعبة Merge boss ⭐️", "https://s.click.aliexpress.com/e/_DlCyg5Z"),
        ("⭐️ لعبة Fantastic Farm ⭐️", "https://s.click.aliexpress.com/e/_DBBkt9V"),
        ("⭐️ لعبة قلب الاوراق Flip ⭐️", "https://s.click.aliexpress.com/e/_DdcXZ2r"),
        ("⭐️ لعبة GoGo Match ⭐️", "https://s.click.aliexpress.com/e/_DDs7W5D")
    ]
    for text, url in games:
        keyboard_games.add(types.InlineKeyboardButton(text, url=url))
    
    return keyboard_start, keyboard_games

keyboard_start, keyboard_games = create_keyboards()

# Handlers
@bot.message_handler(commands=['start'])
def welcome(message):
    bot.send_message(
        message.chat.id,
        "مرحبا بك، ارسل لنا رابط المنتج الذي تريد شرائه لنوفر لك افضل سعر له 👌\n",
        reply_markup=keyboard_start
    )

@bot.callback_query_handler(func=lambda call: call.data == 'click')
def handle_click(call):
    text = """✅1-ادخل الى السلة من هنا:
https://s.click.aliexpress.com/e/_opGCtMf 
✅2-قم باختيار المنتجات التي تريد تخفيض سعرها
✅3-اضغط على زر دفع ليحولك لصفحة التأكيد 
✅4-اضغط على الايقونة في الاعلى وانسخ الرابط هنا في البوت لتتحصل على رابط التخفيض"""
    
    bot.send_photo(
        call.message.chat.id,
        "https://i.postimg.cc/HkMxWS1T/photo-5893070682508606111-y.jpg",
        caption=text,
        reply_markup=keyboard_start
    )

@bot.callback_query_handler(func=lambda call: call.data == 'games')
def handle_games(call):
    bot.send_photo(
        call.message.chat.id,
        "https://i.postimg.cc/zvDbVTS0/photo-5893070682508606110-x.jpg",
        caption="روابط ألعاب جمع العملات المعدنية لإستعمالها في خفض السعر لبعض المنتجات، قم بالدخول يوميا لها للحصول على أكبر عدد ممكن في اليوم 👇",
        reply_markup=keyboard_games
    )

# Fonctions utilitaires
def extract_link(text):
    pattern = r'https?://\S+|www\.\S+'
    links = re.findall(pattern, text)
    return links[0] if links else None

def build_shopcart_link(link):
    params = parse_qs(urlparse(link).query)
    shop_cart_link = "https://www.aliexpress.com/p/trade/confirm.html?"
    shop_cart_params = {
        "availableProductShopcartIds": ",".join(params["availableProductShopcartIds"]),
        "extraParams": json.dumps({"channelInfo": {"sourceType": "620"}}, separators=(',', ':'))
    }
    return shop_cart_link + urllib.parse.urlencode(shop_cart_params)

def get_product_info(link):
    try:
        product = aliexpress.get_products_details([link])[0]
        return {
            'image': product.product_main_image_url,
            'price': product.target.sale_price,
            'title': product.product_title
        }
    except:
        return None

def get_affiliate_links(link):
    try:
        links = aliexpress.get_affiliate_links(
            f'https://star.aliexpress.com/share/share.htm?platform=AE&businessType=ProductDetail&redirectUrl={link}'
        )
        return [link.promotion_link for link in links]
    except:
        return None

# Handler principal
@bot.message_handler(func=lambda message: True)
def handle_message(message):
    link = extract_link(message.text)
    if not link or "aliexpress.com" not in link:
        bot.send_message(
            message.chat.id,
            "الرابط غير صحيح! تأكد من رابط المنتج أو اعد المحاولة.\n قم بإرسال الرابط فقط بدون عنوان المنتج",
            parse_mode='HTML'
        )
        return

    sent_msg = bot.send_message(message.chat.id, 'المرجو الانتظار قليلا، يتم تجهيز العروض ⏳')

    try:
        if "availableProductShopcartIds" in message.text:
            shopcart_link = build_shopcart_link(link)
            affiliate_link = aliexpress.get_affiliate_links(shopcart_link)[0].promotion_link
            bot.send_photo(
                message.chat.id,
                "https://i.postimg.cc/HkMxWS1T/photo-5893070682508606111-y.jpg",
                caption=f"هذا رابط تخفيض السلة \n{affiliate_link}"
            )
        else:
            product_info = get_product_info(link)
            affiliate_links = get_affiliate_links(link)
            
            if not affiliate_links:
                raise Exception("Could not get affiliate links")

            if product_info:
                caption = f"""🛒 منتجك هو: 🔥
{product_info['title']} 🛍
سعر المنتج: {product_info['price']} دولار 💵

قارن بين الاسعار واشتري 🔥
💰 عرض العملات (السعر النهائي عند الدفع):
الرابط {affiliate_links[0]} 
💎 عرض السوبر:
الرابط {affiliate_links[1] if len(affiliate_links) > 1 else 'N/A'}
♨️ عرض محدود:
الرابط {affiliate_links[2] if len(affiliate_links) > 2 else 'N/A'}

#AliXPromotion ✅"""
                
                bot.send_photo(
                    message.chat.id,
                    product_info['image'],
                    caption=caption,
                    reply_markup=keyboard_start
                )
            else:
                bot.send_message(
                    message.chat.id,
                    f"""قارن بين الاسعار واشتري 🔥
💰 عرض العملات (السعر النهائي عند الدفع):
الرابط {affiliate_links[0]}
💎 عرض السوبر:
الرابط {affiliate_links[1] if len(affiliate_links) > 1 else 'N/A'}
♨️ عرض محدود:
الرابط {affiliate_links[2] if len(affiliate_links) > 2 else 'N/A'}

#AliXPromotion ✅""",
                    reply_markup=keyboard_start
                )
    except Exception as e:
        bot.send_message(message.chat.id, "حدث خطأ أثناء معالجة طلبك 🤷🏻‍♂️")
    finally:
        bot.delete_message(message.chat.id, sent_msg.message_id)

# Démarrer le serveur web et le bot
if __name__ == "__main__":
    keep_alive()
    bot.infinity_polling(timeout=10, long_polling_timeout=5)
