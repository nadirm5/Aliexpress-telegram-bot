from flask import Flask
from threading import Thread
import requests
import time
import logging
from waitress import serve  # Serveur de production WSGI

app = Flask(__name__)

# Configuration du logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

@app.route('/')
def home():
    """Endpoint de santé"""
    return "🤖 Bot AliExpress Telegram en fonctionnement", 200

def run_server():
    """Lance le serveur de production"""
    logger.info("Démarrage du serveur Waitress sur le port 8080")
    serve(app, host="0.0.0.0", port=8080)

def ping_application():
    """Ping périodique pour maintenir l'application active"""
    while True:
        try:
            response = requests.get(
                "https://aliexpress-telegram-bot-qjdv.onrender.com",
                timeout=10
            )
            if response.status_code == 200:
                logger.info("Ping réussi - Application maintenue active")
            else:
                logger.warning(f"Ping échoué - Code: {response.status_code}")
        except Exception as e:
            logger.error(f"Échec du ping: {str(e)}")
        
        # Attendre 5 minutes entre chaque ping
        time.sleep(60 * 5)

def keep_alive():
    """Initialise les services de maintien en vie"""
    # Démarrer le serveur web
    server_thread = Thread(target=run_server, daemon=True)
    server_thread.start()
    
    # Démarrer le service de ping
    ping_thread = Thread(target=ping_application, daemon=True)
    ping_thread.start()
    
    logger.info("Tous les services keep-alive sont opérationnels")

if __name__ == '__main__':
    keep_alive()
    
    # Maintenir le thread principal actif
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Arrêt du système keep-alive")
