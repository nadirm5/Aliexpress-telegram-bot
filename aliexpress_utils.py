import aiohttp
import re
import asyncio

async def get_product_details_by_id(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/113.0.0.0 Safari/537.36"
    }

    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as resp:
            if resp.status != 200:
                return "Erreur HTTP", "Erreur HTTP"
            html = await resp.text()

            # Prix réduit via JSON ou texte brut
            price_match = re.search(r'"salePrice":"(.*?)"', html) or re.search(r'"price":"(.*?)"', html)
            shipping_match = re.search(r'"shippingFee":"(.*?)"', html)

            price = price_match.group(1) + " USD" if price_match else "Prix non trouvé"
            shipping = shipping_match.group(1) + " USD" if shipping_match else "Livraison non trouvée"

            return price, shipping
