from flask import Flask, request
import telebot
import requests

# Configuration
API_TOKEN = '7193442605:AAGRl9j40eNn6Hu5uvWejlxnzuAjwg6Yp0M'
APP_KEY = '506592'
APP_SECRET = 'ggkzfJ7lilLc7OXs6khWfT4qTZdZuJbh'
TRACKING_ID = 'default'

bot = telebot.TeleBot(API_TOKEN)
app = Flask(__name__)

# Fonction pour récupérer l'ID produit depuis un lien court AliExpress
def get_product_id_from_short_url(short_url):
    try:
        response = requests.get(short_url, allow_redirects=True, timeout=10)
        redirect_url = response.url
        if "aliexpress.com/item/" in redirect_url:
            return redirect_url.split("/")[-1].split(".")[0]
        elif "product/" in redirect_url:
            return redirect_url.split("product/")[1].split(".html")[0]
    except Exception as e:
        print("Erreur:", e)
    return None

# Fonction pour générer un message complet avec les infos produit
def generer_message_produit(pid):
    from aliexpress_api_client import AliexpressApiClient

    client = AliexpressApiClient(APP_KEY, APP_SECRET)
    try:
        result = client.get_product_detail(product_id=pid, target_currency='USD', tracking_id=TRACKING_ID)
        if not result:
            return "Produit introuvable."

        item = result['product']
        titre = item['title']
        prix = item['original_price']
        promo = item.get('sale_price', prix)
        reduction = round((1 - float(promo)/float(prix)) * 100, 1)
        vente = item.get("orders", "N/A")
        note = item.get("rating", "N/A")
        lien = item['promotion_link']

        msg = f"""🛒 <b>{titre}</b>

💰 Prix : <s>{prix} $</s> ➜ <b>{promo} $</b>
🔥 Remise : <b>{reduction}%</b>
📦 Ventes : {vente}
⭐ Note : {note}

🔗 <a href="{lien}">Acheter maintenant</a> (lien affilié)
        """
        return msg
    except Exception as e:
        print("Erreur API:", e)
        return "Erreur lors de la récupération des infos produit."

# Réponse Telegram
@bot.message_handler(func=lambda message: True)
def handle_message(message):
    lien = message.text.strip()
    if "aliexpress.com" not in lien:
        bot.reply_to(message, "Merci d'envoyer un lien AliExpress.")
        return

    pid = get_product_id_from_short_url(lien)
    if not pid:
        bot.reply_to(message, "Impossible de récupérer l'ID du produit.")
        return

    msg = generer_message_produit(pid)
    bot.send_message(message.chat.id, msg, parse_mode='HTML', disable_web_page_preview=False)

# Route pour garder Render.com actif
@app.route('/')
def home():
    return 'Bot AliExpress Affiliation OK!'

@app.route('/' + API_TOKEN, methods=['POST'])
def webhook():
    bot.process_new_updates([telebot.types.Update.de_json(request.stream.read().decode("utf-8"))])
    return '', 200

# Webhook pour Render
def start_webhook():
    bot.remove_webhook()
    bot.set_webhook(url='https://TON-LIEN-RENDER.onrender.com/' + API_TOKEN)

if __name__ == "__main__":
    start_webhook()
    app.run(host="0.0.0.0", port=10000)
