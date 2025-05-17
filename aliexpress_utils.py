import requests
from bs4 import BeautifulSoup
import re

def extract_product_id(url):
    """Extrait l'ID produit depuis une URL AliExpress"""
    match = re.search(r'/item/(\d+)\.html', url)
    return match.group(1) if match else None

def get_aliexpress_product_info(product_url):
    """Récupère nom et image du produit depuis AliExpress"""
    product_name = None
    img_url = None
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        cookies = {"x-hng": "lang=en-US", "intl_locale": "en_US"}
        response = requests.get(product_url, headers=headers, cookies=cookies, timeout=15)
        if response.status_code != 200:
            print(f"Erreur chargement page : {response.status_code}")
            return None, None
        soup = BeautifulSoup(response.text, "html.parser")

        # Recherche titre produit dans plusieurs endroits
        selectors = [
            "div#root div > div:nth-of-type(1) > div > div:nth-of-type(1) > div:nth-of-type(1) > div:nth-of-type(2) > div:nth-of-type(4) > h1",
            "meta[property='og:title']",
            "meta[name='keywords']",
            "h1[data-pl='product-title']",
            "h1[class*='product-title-text']",
            "h1"
        ]

        for sel in selectors:
            if sel.startswith("meta"):
                tag = soup.select_one(sel)
                if tag and tag.has_attr("content"):
                    product_name = tag["content"]
                    break
            else:
                tag = soup.select_one(sel)
                if tag:
                    product_name = tag.get_text(strip=True)
                    break

        # Nettoyage du nom
        if product_name:
            product_name = re.sub(r'\s*-\s*AliExpress(\s+\d+)?$', '', product_name).strip()
            product_name = re.sub(r'-AliExpress(\s+\d+)?$', '', product_name).strip()

        # Image principale
        img_tag = soup.find("img", {"class": lambda x: x and "magnifier--image" in x})
        if img_tag and img_tag.has_attr("src"):
            img_url = img_tag["src"]
        else:
            meta_img = soup.find("meta", property="og:image")
            if meta_img and meta_img.has_attr("content"):
                img_url = meta_img["content"]

        return product_name, img_url
    except Exception as e:
        print(f"Erreur get_aliexpress_product_info: {e}")
        return None, None

def get_product_details_by_id(product_id):
    """Construit l'URL produit à partir de l'ID et récupère les détails"""
    product_url = f"https://www.aliexpress.com/item/{product_id}.html"
    print(f"URL construite: {product_url}")
    return get_aliexpress_product_info(product_url)

def check_bundle_deals(product_id):
    """Vérifie la présence de bundle deals pour un produit"""
    bundle_url = (
        f"https://www.aliexpress.com/ssr/300000512/BundleDeals2"
        f"?productIds={product_id}&disableNav=YES&_immersiveMode=true"
    )
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        response = requests.get(bundle_url, headers=headers, timeout=10)
        if response.status_code != 200:
            print("Page bundle non accessible.")
            return False
        text = response.text.lower()
        if "bundle deals" in text or "bundle price" in text:
            return True
        soup = BeautifulSoup(response.text, "html.parser")
        if soup.find_all(string=lambda s: s and "bundle price" in s):
            return True
        return False
    except Exception as e:
        print(f"Erreur check_bundle_deals: {e}")
        return False

def generate_bundle_deal_link(product_id, tracking_id="default"):
    """Génère un lien bundle deal avec tracking"""
    return (
        f"https://www.aliexpress.com/ssr/300000512/BundleDeals2"
        f"?productIds={product_id}&disableNav=YES&_immersiveMode=true"
        f"&aff_short_key={tracking_id}&afSmartRedirect=y"
    )

# Exemple d'utilisation dans un bot

def prepare_message_from_url(product_url, tracking_id="default"):
    product_id = extract_product_id(product_url)
    if not product_id:
        return "❌ Impossible d'extraire l'ID produit depuis l'URL."

    name, img = get_product_details_by_id(product_id)
    has_bundle = check_bundle_deals(product_id)
    bundle_link = generate_bundle_deal_link(product_id, tracking_id) if has_bundle else None

    product_data = {
        "title": name or "Produit inconnu",
        "price": None,  # Tu peux intégrer un scraper ou API pour le prix
        "currency": ""
    }
    generated_links = {
        "coin": product_url,  # lien normal du produit, par exemple
        "bundle": bundle_link
    }

    message = _build_response_message(product_data, generated_links, details_source="API")
    return message

# N’oublie pas d’importer ou définir ta fonction _build_response_message
