# keep_alive.py


from flask import Flask, request
from threading import Thread
import requests
import time

app = Flask(__name__)

@app.route('/')
def home():
    return "?"

@app.route('/callback')
def callback():
    code = request.args.get('code')
    if not code:
        return "No code received", 400
    return "Callback received with code: " + code

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

def self_ping():
    while True:
        try:
            requests.get("https://aliexpress-telegram-bot-qjdv.onrender.com")
            print(" hello world ")
        except:
            print("fail ping")
        time.sleep(60 * 3)

keep_alive()
Thread(target=self_ping).start()
