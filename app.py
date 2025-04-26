#!/usr/bin/env python
# coding: utf-8

import telebot
from telebot import types
from aliexpress_api import AliexpressApi, models
import re
import requests, json
import urllib.parse
from urllib.parse import urlparse, parse_qs

# Initialisation du bot
bot = telebot.TeleBot('6613740819:AAEiGrOSCcuVNQTrzkhbJ4Bg29oBm6UU6nw')

# Initialisation de l'API AliExpress
aliexpress = AliexpressApi('502336', 'qW3MlLGKtt7jnZOg8KkHpfCbTaac2LOq',
                           models.Language.EN, models.Currency.EUR, 'default')

# Clavier de démarrage
keyboardStart = types.InlineKeyboardMarkup(row_width=1)
btn1 = types.InlineKeyboardButton("⭐️ألعاب لجمع العملات المعدنية⭐️", callback_data="games")
btn2 = types.InlineKeyboardButton("⭐️تخفيض العملات على منتجات السلة 🛒⭐️", callback_data='click')
btn3 = types.InlineKeyboardButton("❤️ اشترك في القناة للمزيد من العروض ❤️", url="https://t.me/AliXPromotion")
btn4 = types.InlineKeyboardButton("🎬 شاهد كيفية عمل البوت 🎬", url="https://t.me/AliXPromotion/8")
btn5 = types.InlineKeyboardButton("💰  حمل تطبيق Aliexpress عبر الضغط هنا للحصول على مكافأة 5 دولار  💰", url="https://a.aliexpress.com/_mtV0j3q")
keyboardStart.add(btn1, btn2, btn3, btn4, btn5)

# Clavier normal
keyboard = types.InlineKeyboardMarkup(row_width=1)
keyboard.add(btn1, btn2, btn3)

# Clavier jeux
keyboard_games = types.InlineKeyboardMarkup(row_width=1)
keyboard_games.add(
    types.InlineKeyboardButton(" ⭐️ صفحة مراجعة وجمع النقاط يوميا ⭐️", url="https://s.click.aliexpress.com/e/_on0MwkF"),
    types.InlineKeyboardButton("⭐️ لعبة Merge boss ⭐️", url="https://s.click.aliexpress.com/e/_DlCyg5Z"),
    types.InlineKeyboardButton("⭐️ لعبة Fantastic Farm ⭐️", url="https://s.click.aliexpress.com/e/_DBBkt9V"),
    types.InlineKeyboardButton("⭐️ لعبة قلب الاوراق Flip ⭐️", url="https://s.click.aliexpress.com/e/_DdcXZ2r"),
    types.InlineKeyboardButton("⭐️ لعبة GoGo Match ⭐️", url="https://s.click.aliexpress.com/e/_DDs7W5D")
)

@bot.message_handler(commands=['start'])
def welcome_user(message):
    bot.send_message(message.chat.id,
                     "مرحبا بك، ارسل لنا رابط المنتج الذي تريد شرائه لنوفر لك افضل سعر له 👌 \n",
                     reply_markup=keyboardStart)

@bot.callback_query_handler(func=lambda call: call.data == 'click')
def button_click(callback_query):
    bot.edit_message_text(chat_id=callback_query.message.chat.id,
                          message_id=callback_query.message.message_id,
                          text="...")
    text = "✅1-ادخل الى السلة من هنا:\n" \
           " https://s.click.aliexpress.com/e/_opGCtMf \n" \
           "✅2-قم باختيار المنتجات التي تريد تخفيض سعرها\n" \
           "✅3-اضغط على زر دفع ليحولك لصفحة التأكيد \n" \
           "✅4-اضغط على الايقونة في الاعلى وانسخ الرابط  هنا في البوت لتتحصل على رابط التخفيض"
    img_link1 = "https://i.postimg.cc/HkMxWS1T/photo-5893070682508606111-y.jpg"
    bot.send_photo(callback_query.message.chat.id, img_link1, caption=text, reply_markup=keyboard)

def get_affiliate_links(message, message_id, link):
    try:
        affiliate_link = aliexpress.get_affiliate_links(link)[0].promotion_link
        super_links = aliexpress.get_affiliate_links(link)[0].promotion_link
        limit_links = aliexpress.get_affiliate_links(link)[0].promotion_link

        try:
            details = aliexpress.get_products_details([link])[0]
            title = details.product_title
            price = details.target.sale_price
            image = details.product_main_image_url

            bot.delete_message(message.chat.id, message_id)
            bot.send_photo(message.chat.id, image,
                           caption=f"🛒 منتجك هو  : 🔥 \n"
                                   f"{title} 🛍 \n"
                                   f"سعر المنتج : {price} دولار 💵\n"
                                   f"💰 عرض العملات : {affiliate_link} \n"
                                   f"💎 عرض السوبر : {super_links} \n"
                                   f"♨️ عرض محدود : {limit_links} \n\n"
                                   "#AliXPromotion ✅",
                           reply_markup=keyboard)

        except:
            bot.delete_message(message.chat.id, message_id)
            bot.send_message(message.chat.id,
                             f"💰 عرض العملات : {affiliate_link} \n"
                             f"💎 عرض السوبر : {super_links} \n"
                             f"♨️ عرض محدود : {limit_links} \n\n"
                             "#AliXPromotion ✅",
                             reply_markup=keyboard)
    except:
        bot.send_message(message.chat.id, "حدث خطأ 🤷🏻‍♂️")

def extract_link(text):
    match = re.search(r'(https?://[^\s]+)', text)
    return match.group(0) if match else None

def build_shopcart_link(link):
    params = get_url_params(link)
    shop_cart_link = "https://www.aliexpress.com/p/trade/confirm.html?"
    shop_cart_params = {
        "availableProductShopcartIds": ",".join(params["availableProductShopcartIds"]),
        "extraParams": json.dumps({"channelInfo": {"sourceType": "620"}}, separators=(',', ':'))
    }
    return create_query_string_url(link=shop_cart_link, params=shop_cart_params)

def get_url_params(link):
    parsed_url = urlparse(link)
    return parse_qs(parsed_url.query)

def create_query_string_url(link, params):
    return link + urllib.parse.urlencode(params)

def get_affiliate_shopcart_link(link, message):
    try:
        shopcart_link = build_shopcart_link(link)
        affiliate_link = aliexpress.get_affiliate_links(shopcart_link)[0].promotion_link
        img_link3 = "https://i.postimg.cc/HkMxWS1T/photo-5893070682508606111-y.jpg"
        bot.send_photo(message.chat.id, img_link3, caption=f"هذا رابط تخفيض السلة \n{affiliate_link}")
    except:
        bot.send_message(message.chat.id, "حدث خطأ 🤷🏻‍♂️")

@bot.message_handler(func=lambda message: True)
def get_link(message):
    link = extract_link(message.text)
    sent = bot.send_message(message.chat.id, '⏳ يتم تجهيز العروض...')
    message_id = sent.message_id

    if link and "aliexpress.com" in link:
        if "availableProductShopcartIds" in message.text.lower():
            get_affiliate_shopcart_link(link, message)
        else:
            get_affiliate_links(message, message_id, link)
    else:
        bot.delete_message(message.chat.id, message_id)
        bot.send_message(message.chat.id, "❌ الرابط غير صحيح، أرسل رابط منتج فقط", parse_mode="HTML")

@bot.callback_query_handler(func=lambda call: True)
def handle_callback_query(call):
    img_link2 = "https://i.postimg.cc/zvDbVTS0/photo-5893070682508606110-x.jpg"
    bot.send_photo(call.message.chat.id, img_link2,
                   caption="روابط ألعاب جمع العملات 👇",
                   reply_markup=keyboard_games)

# --- keep_alive + polling ---

from flask import Flask
from threading import Thread

app = Flask('')

@app.route('/')
def home():
    return "Bot is online!"

def keep_alive():
    Thread(target=lambda: app.run(host='0.0.0.0', port=8080)).start()

keep_alive()
bot.infinity_polling(timeout=10, long_polling_timeout=5)
