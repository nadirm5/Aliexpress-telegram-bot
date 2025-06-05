# keep_alive.py


from flask import Flask, request
import requests

app = Flask(__name__)

@app.route('/callback')
def callback():
    code = request.args.get('code')
    if not code:
        return "No code received", 400

    app_key = '506592'          # Ta clé API AliExpress
    app_secret = 'ggkzfJ7lilLc7OXs6khWfT4qTZdZuJbh'   # Ton App Secret AliExpress
    redirect_uri = 'https://aliexpress-telegram-bot-qjdv.onrender.com/callback'

    token_url = 'https://oauth.aliexpress.com/token'

    data = {
        'grant_type': 'authorization_code',
        'code': code,
        'client_id': app_key,
        'client_secret': app_secret,
        'redirect_uri': redirect_uri
    }

    response = requests.post(token_url, data=data)

    if response.status_code == 200:
        token_data = response.json()
        access_token = token_data.get('access_token')
        if access_token:
            return f"Access token: {access_token}"
        else:
            return "Token non trouvé dans la réponse.", 500
    else:
        return f"Erreur lors de la récupération du token: {response.text}", response.status_code

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
