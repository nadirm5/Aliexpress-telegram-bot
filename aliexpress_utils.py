import requests
from bs4 import BeautifulSoup
import re
import json

def get_price_after_discount_kr(product_id):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9"
    }
    cookies = {
        "intl_locale": "en_US",
        "aep_usuc_f": "region=DZ",  # Livraison en Algérie
        "x-locale": "en_US",
        "x-country": "KR"  # Pays Corée pour afficher prix en KRW
    }
    
    url = f"https://www.aliexpress.com/item/{product_id}.html"
    response = requests.get(url, headers=headers, cookies=cookies, timeout=15)
    if response.status_code != 200:
        print(f"Erreur chargement page: {response.status_code}")
        return None

    soup = BeautifulSoup(response.text, "html.parser")

    price_after_discount = None

    # Chercher le prix visible sur la page (classe possible)
    price_tag = soup.find("span", class_=lambda x: x and ("product-price-value" in x or "product-price-current" in x))
    if price_tag:
        price_after_discount = price_tag.get_text(strip=True)

    # Si pas trouvé, chercher dans les scripts JS la variable window.runParams
    if not price_after_discount:
        scripts = soup.find_all("script")
        for script in scripts:
            if script.string and "window.runParams" in script.string:
                m = re.search(r'window\.runParams\s*=\s*(\{.*?\});', script.string, re.DOTALL)
                if m:
                    try:
                        data = json.loads(m.group(1))
                        price_after_discount = data['data']['priceModule']['formatedActivityPrice']
                    except Exception as e:
                        print("Erreur extraction prix JSON:", e)
                break

    return price_after_discount

def get_product_details_by_id(product_id):
    return get_price_after_discount_kr(product_id)
