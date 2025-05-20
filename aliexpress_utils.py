import requests
from bs4 import BeautifulSoup
import re

def get_aliexpress_product_info(product_id):
    """
    Tente d'extraire les infos produit depuis la version mobile (plus simple), puis desktop si nécessaire.
    Retourne nom, image, prix
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X)"
    }

    # 1. VERSION MOBILE
    mobile_url = f"https://m.aliexpress.com/item/{product_id}.html"
    try:
        r = requests.get(mobile_url, headers=headers, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")

        # Nom
        name_tag = soup.find("h1")
        product_name = name_tag.get_text(strip=True) if name_tag else None

        # Image
        img_tag = soup.find("img")
        img_url = img_tag["src"] if img_tag and img_tag.has_attr("src") else None

        # Prix
        price_tag = soup.find("span", class_=lambda x: x and "product-price-value" in x)
        if not price_tag:
            price_tag = soup.find("span", class_=lambda x: x and "price" in x)
        product_price = price_tag.get_text(strip=True) if price_tag else None

        # Si les infos sont trouvées, retourne
        if product_name and product_price:
            return product_name, img_url, product_price
    except Exception as e:
        print(f"[Mobile] Erreur: {e}")

    # 2. VERSION DESKTOP si mobile échoue
    try:
        desktop_url = f"https://vi.aliexpress.com/item/{product_id}.html"
        r = requests.get(desktop_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")

        # Nom
        h1 = soup.find("h1")
        product_name = h1.get_text(strip=True) if h1 else None

        # Image
        meta_img = soup.find("meta", property="og:image")
        img_url = meta_img["content"] if meta_img and meta_img.has_attr("content") else None

        # Prix depuis script JSON
        product_price = None
        for script in soup.find_all("script"):
            if script.string and "discountPrice" in script.string:
                match = re.search(r'"discountPrice"\s*:\s*"([\d.,\sDA$€]+)"', script.string)
                if match:
                    product_price = match.group(1).strip()
                    break

        return product_name, img_url, product_price
    except Exception as e:
        print(f"[Desktop] Erreur: {e}")
        return None, None, None
