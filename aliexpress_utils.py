import aiohttp
from bs4 import BeautifulSoup
import asyncio

async def fetch_product_price(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)"
                      " Chrome/113.0.0.0 Safari/537.36"
    }
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as resp:
            if resp.status != 200:
                print(f"Erreur HTTP: {resp.status}")
                return None
            html = await resp.text()

            soup = BeautifulSoup(html, 'html.parser')

            # Exemple : récupérer le prix réduit (sélecteur à ajuster selon la page)
            price_elem = soup.select_one('div.product-price-current span')
            if not price_elem:
                price_elem = soup.select_one('span.product-price-value')

            # Récupérer la livraison (souvent dans un span ou div avec 'shipping' dans la classe)
            shipping_elem = soup.find(lambda tag: tag.name in ['span','div'] and 'shipping' in (tag.get('class') or []))

            price = price_elem.get_text(strip=True) if price_elem else "Prix non trouvé"
            shipping = shipping_elem.get_text(strip=True) if shipping_elem else "Livraison non trouvée"

            print(f"Prix réduit: {price}")
            print(f"Livraison: {shipping}")

            return price, shipping

# Exemple d'utilisation
url = "https://www.aliexpress.com/item/1005005551234567.html"  # Remplace par ton URL
asyncio.run(fetch_product_price(url))
