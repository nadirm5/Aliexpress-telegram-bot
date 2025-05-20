import requests
from bs4 import BeautifulSoup
import re

def get_aliexpress_product_info(product_url):
    """
    Extract product name and main image URL from AliExpress without Selenium
    Args:
        product_url (str): AliExpress product page URL
    Returns:
        tuple: (product_name (str or None), img_url (str or None))
    """
    product_name = None
    img_url = None
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        }
        cookies = {"x-hng": "lang=en-US", "intl_locale": "en_US"}

        response = requests.get(product_url, headers=headers, cookies=cookies, timeout=15)
        if response.status_code != 200:
            print(f"Failed to load page: HTTP {response.status_code}")
            return None, None

        soup = BeautifulSoup(response.text, "html.parser")

        # 1) Essayer d'extraire le nom via un chemin spécifique
        root_div = soup.find("div", id="root")
        if root_div:
            h1 = root_div.select_one(
                "div > div:nth-of-type(1) > div > div:nth-of-type(1) > div:nth-of-type(1) > div:nth-of-type(2) > div:nth-of-type(4) > h1"
            )
            if h1:
                product_name = h1.get_text(strip=True)

        # 2) Sinon fallback sur meta og:title
        if not product_name:
            meta_title = soup.find("meta", property="og:title")
            if meta_title and meta_title.has_attr("content"):
                product_name = meta_title["content"]

        # 3) Sinon fallback sur keywords meta
        if not product_name:
            meta_name = soup.find("meta", attrs={"name": "keywords"})
            if meta_name and meta_name.has_attr("content"):
                product_name = meta_name["content"].split(",")[0].strip()

        # 4) Sinon h1 avec data-pl=product-title
        if not product_name:
            h1 = soup.find("h1", {"data-pl": "product-title"})
            if h1:
                product_name = h1.get_text(strip=True)

        # 5) Sinon h1 avec classe contenant product-title-text ou product-title
        if not product_name:
            h1 = soup.find("h1", {"class": lambda x: x and ("product-title-text" in x or "product-title" in x)})
            if h1:
                product_name = h1.get_text(strip=True)

        # 6) Sinon dernier recours h1 générique
        if not product_name:
            h1 = soup.find("h1")
            if h1:
                product_name = h1.get_text(strip=True)

        # Extraction de l'image principale
        img_tag = soup.find("img", {"class": lambda x: x and "magnifier--image" in x})
        if img_tag and img_tag.has_attr("src"):
            img_url = img_tag["src"]
        else:
            meta_img = soup.find("meta", property="og:image")
            if meta_img and meta_img.has_attr("content"):
                img_url = meta_img["content"]

        # Nettoyage du nom produit
        if product_name:
            product_name = re.sub(r'\s*-\s*AliExpress(\s+\d+)?$', '', product_name).strip()
            product_name = re.sub(r'-AliExpress(\s+\d+)?$', '', product_name).strip()

        return product_name, img_url

    except Exception as e:
        print(f"An error occurred in get_aliexpress_product_info: {str(e)}")
        return None, None


def get_product_details_by_id(product_id):
    """
    Construire l'URL à partir de l'ID produit et récupérer nom et image.
    Args:
        product_id (str or int): AliExpress product ID
    Returns:
        tuple: (product_name, img_url) ou (None, None) si erreur
    """
    product_url = f"https://vi.aliexpress.com/item/{product_id}.html"
    print(f"Constructed URL: {product_url}")
    return get_aliexpress_product_info(product_url)
