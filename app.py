import telebot
from telebot import types
from aliexpress_api import AliexpressApi, models
import re
import requests, json
from urllib.parse import urlparse, parse_qs
import time
from flask import Flask
from threading import Thread

# Création du bot Telegram
bot = telebot.TeleBot('6613740819:AAEiGrOSCcuVNQTrzkhbJ4Bg29oBm6UU6nw')

# Configuration de l'API AliExpress
aliexpress = AliexpressApi('502336', 'qW3MlLGKtt7jnZOg8KkHpfCbTaac2LOq', models.Language.EN, models.Currency.EUR, 'default')

# Clavier d'accueil
keyboardStart = types.InlineKeyboardMarkup(row_width=1)
btn1 = types.InlineKeyboardButton("⭐️ألعاب لجمع العملات المعدنية⭐️", callback_data="games")
btn2 = types.InlineKeyboardButton("⭐️تخفيض العملات على منتجات السلة 🛒⭐️", callback_data='click')
btn4 = types.InlineKeyboardButton("🎬 شاهد كيفية عمل البوت 🎬", url="https://t.me/AliXPromotion/8")
btn5 = types.InlineKeyboardButton("💰  حمل تطبيق Aliexpress عبر الضغط هنا للحصول على مكافأة 5 دولار  💰", url="https://a.aliexpress.com/_mtV0j3q")
keyboardStart.add(btn1, btn2, btn4, btn5)

# Clavier pour les jeux
keyboard_games = types.InlineKeyboardMarkup(row_width=1)
btn1 = types.InlineKeyboardButton(" ⭐️ صفحة مراجعة وجمع النقاط يوميا ⭐️", url="https://s.click.aliexpress.com/e/_on0MwkF")
btn2 = types.InlineKeyboardButton("⭐️ لعبة Merge boss ⭐️", url="https://s.click.aliexpress.com/e/_DlCyg5Z")
btn3 = types.InlineKeyboardButton("⭐️ لعبة Fantastic Farm ⭐️", url="https://s.click.aliexpress.com/e/_DBBkt9V")
btn4 = types.InlineKeyboardButton("⭐️ لعبة قلب الاوراق Flip ⭐️", url="https://s.click.aliexpress.com/e/_DdcXZ2r")
btn5 = types.InlineKeyboardButton("⭐️ لعبة GoGo Match ⭐️", url="https://s.click.aliexpress.com/e/_DDs7W5D")
keyboard_games.add(btn1, btn2, btn3, btn4, btn5)

# Fonction d'accueil
@bot.message_handler(commands=['start'])
def welcome_user(message):
    bot.send_message(message.chat.id, "مرحبا بك، ارسل لنا رابط المنتج الذي تريد شرائه لنوفر لك افضل سعر له 👌 \n", reply_markup=keyboardStart)

# Fonction de gestion des callback pour les boutons
@bot.callback_query_handler(func=lambda call: call.data == 'click')
def button_click(callback_query):
    bot.edit_message_text(chat_id=callback_query.message.chat.id, message_id=callback_query.message.message_id, text="...")
    text = "✅1-ادخل الى السلة من هنا:\n https://s.click.aliexpress.com/e/_opGCtMf \n✅2-قم باختيار المنتجات التي تريد تخفيض سعرها\n✅3-اضغط على زر دفع ليحولك لصفحة التأكيد \n✅4-اضغط على الايقونة في الاعلى وانسخ الرابط هنا في البوت لتتحصل على رابط التخفيض"
    img_link1 = "https://i.postimg.cc/HkMxWS1T/photo-5893070682508606111-y.jpg"
    bot.send_photo(callback_query.message.chat.id, img_link1, caption=text, reply_markup=keyboard)

# Fonction pour récupérer les liens affiliés
def get_affiliate_links(message, message_id, link):
    try:
        limit_links = aliexpress.get_affiliate_links(f'https://star.aliexpress.com/share/share.htm?platform=AE&businessType=ProductDetail&redirectUrl={link}?sourceType=561&aff_fcid=')
        limit_links = limit_links[0].promotion_link
        try:
            img_link = aliexpress.get_products_details(['1000006468625', f'https://star.aliexpress.com/share/share.htm?platform=AE&businessType=ProductDetail&redirectUrl={link}'])
            price_pro = img_link[0].target.sale_price
            title_link = img_link[0].product_title
            img_link = img_link[0].product_main_image_url
            bot.delete_message(message.chat.id, message_id)
            bot.send_photo(message.chat.id, img_link, caption=f"🛒 منتجك هو  : 🔥 \n {title_link} 🛍 \n سعر المنتج  : {price_pro} دولار 💵\n قارن بين الاسعار واشتري 🔥 \n 💰 عرض العملات (السعر النهائي عند الدفع)  : \nالرابط {affiliate_link} \n💎 عرض السوبر  : \nالرابط {super_links} \n♨️ عرض محدود  : \nالرابط {limit_links} \n\n #AliXPromotion ✅", reply_markup=keyboard)
        except:
            bot.delete_message(message.chat.id, message_id)
            bot.send_message(message.chat.id, f"قارن بين الاسعار واشتري 🔥 \n💰 عرض العملات (السعر النهائي عند الدفع) : \nالرابط {affiliate_link} \n💎 عرض السوبر : \nالرابط {super_links} \n♨️ عرض محدود : \nالرابط {limit_links} \n\n#AliXPromotion ✅", reply_markup=keyboard)
    except:
        bot.send_message(message.chat.id, "حدث خطأ 🤷🏻‍♂️")

# Fonction pour extraire les liens
def extract_link(text):
    link_pattern = r'https?://\S+|www\.\S+'
    links = re.findall(link_pattern)
    if links:
        return links[0]

# Flask pour maintenir le bot en ligne
app = Flask('')

@app.route('/')
def home():
    return 'Bot is running'

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

def infinity_polling(timeout=10, long_polling_timeout=5):
    while True:
        try:
            bot.polling(none_stop=True, interval=long_polling_timeout)
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(timeout)

# Démarrez le serveur pour garder le bot en vie
keep_alive()

# Démarrez le polling infini
infinity_polling(timeout=10, long_polling_timeout=5)
