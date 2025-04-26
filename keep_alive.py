# keep_alive.py



from flask import Flask

from threading import Thread

import requests

import time



app = Flask(__name__)



@app.route('/')

def home():

    return "?"



def run():

    app.run(host='0.0.0.0', port=8080)



def keep_alive():

    t = Thread(target=run)

    t.start()



def self_ping():

    while True:

        try:

            requests.get("https://aliexpress-affiliate-telegram-bot-1jv9.onrender.com")  

            print(" hello world ")

        except:

            print("fail ping")

        time.sleep(60 * 3)

		

		

		

keep_alive()

Thread(target=self_ping).start()		
