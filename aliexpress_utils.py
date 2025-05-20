import requests
from bs4 import BeautifulSoup
import re
import json

def get_price_after_discount(product_id):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    cookies = {
        "intl_locale": "en_US",    # Langue anglaise
        "aep_usuc_f": "region=DZ", # Livraison Algérie
        "x-locale": "en_US",
        "x-country": "DZ"
    }
    
    url = f"https://www.aliexpress.com/item/{product_id}.html"
    response = requests.get(url, headers=headers, cookies=cookies)
    if response.status_code != 200:
        print("Failed to load page")
        return None

    soup = BeautifulSoup(response.text, "html.parser")

    # Chercher prix affiché (après réduction)
    price_after_discount = None

    # Exemple classes communes pour prix réduit
    price_tag = soup.find("span", class_=lambda x: x and ("product-price-value" in x or "product-price-current" in x))
    if price_tag:
        price_after_discount = price_tag.get_text(strip=True)

    # Si pas trouvé, essayer dans le script JSON intégré
    if not price_after_discount:
        scripts = soup.find_all("script")
        for script in scripts:
            if script.string and "window.runParams" in script.string:
                m = re.search(r'window\.runParams\s*=\s*(\{.*?\});', script.string, re.DOTALL)
                if m:
                    data = json.loads(m.group(1))
                    try:
                        price_after_discount = data['data']['priceModule']['formatedActivityPrice']
                    except:
                        pass
                break

    return price_after_discount

# Exemple d’utilisation
product_id = "1005006070804083"  # Remplace par ton ID produit
prix_final = get_price_after_discount(product_id)
print("Prix après réduction :", prix_final)
