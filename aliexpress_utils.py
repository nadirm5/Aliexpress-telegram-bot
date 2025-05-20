import requests
from bs4 import BeautifulSoup
import re


def get_aliexpress_product_info(product_url):
    """
    Extrait le nom, l'image et le prix réduit du produit AliExpress (version mobile).
    Args:
        product_url (str): L'URL du produit AliExpress (version mobile).
    Returns:
        tuple: (product_name, img_url, price) ou (None, None, None) en cas d'erreur.
    """
    product_name = None
    img_url = None
    price = None
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; Mobile) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
        }
        response = requests.get(product_url, headers=headers, timeout=15)
        if response.status_code != 200:
            print(f"Échec du chargement de la page: {response.status_code}")
            return None, None, None

        soup = BeautifulSoup(response.text, "html.parser")

        # Nom du produit
        h1 = soup.find("h1")
        if h1:
            product_name = h1.get_text(strip=True)
        if not product_name:
            title_tag = soup.find("title")
            if title_tag:
                product_name = title_tag.get_text(strip=True)

        # Nettoyage du nom
        if product_name:
            product_name = re.sub(r'\s*-\s*AliExpress(\s+\d+)?$', '', product_name).strip()
            product_name = re.sub(r'-AliExpress(\s+\d+)?$', '', product_name).strip()

        # Image du produit
        img_tag = soup.find("img")
        if img_tag and img_tag.has_attr("src"):
            img_url = img_tag["src"]

        # Prix réduit
        price_span = soup.find("span", {"class": lambda x: x and "product-price-value" in x})
        if price_span:
            price = price_span.get_text(strip=True)
        else:
            # Fallback to meta tag
            meta_price = soup.find("meta", {"property": "og:product:price:amount"})
            if meta_price and meta_price.has_attr("content"):
                price = meta_price["content"]

        return product_name, img_url, price

    except Exception as e:
        print(f"Erreur dans get_aliexpress_product_info: {str(e)}")
        return None, None, None


def get_product_details_by_id(product_id):
    """
    Construit l'URL mobile à partir de l'ID produit et récupère les détails.
    Args:
        product_id (str or int): L'identifiant du produit AliExpress.
    Returns:
        tuple: (product_name, img_url, price) ou (None, None, None).
    """
    product_url = f"https://m.aliexpress.com/item/{product_id}.html"
    print(f"URL construite : {product_url}")
    return get_aliexpress_product_info(product_url)
