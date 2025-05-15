import requests
from bs4 import BeautifulSoup
import re

def get_aliexpress_product_info(product_url):
    """
    Extract product name and image from AliExpress without Selenium.
    Args:
        product_url (str): AliExpress product page URL.
    Returns:
        tuple: (product_name, img_url)
    """
    product_name = None
    img_url = None
    try:
        headers = {
            # Utiliser un User-Agent mobile améliore les chances de succès
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; Mobile) AliExpressApp"
        }
        cookies = {"x-hng": "lang=en-US", "intl_locale": "en_US"}
        response = requests.get(product_url, headers=headers, cookies=cookies, timeout=15)

        if response.status_code != 200:
            print(f"Échec de chargement de la page: {response.status_code}")
            return None, None

        soup = BeautifulSoup(response.text, "html.parser")

        # Tentatives multiples pour trouver le nom du produit
        selectors = [
            lambda s: s.select_one("h1[data-pl='product-title']"),
            lambda s: s.find("meta", property="og:title"),
            lambda s: s.find("meta", attrs={"name": "keywords"}),
            lambda s: s.find("h1", class_=lambda x: x and "product-title" in x),
            lambda s: s.find("h1"),
        ]

        for selector in selectors:
            result = selector(soup)
            if result:
                if hasattr(result, 'get_text'):
                    product_name = result.get_text(strip=True)
                elif result.has_attr("content"):
                    product_name = result["content"].split(",")[0].strip()
                if product_name:
                    break

        # Nettoyage du nom
        if product_name:
            product_name = re.sub(r'\s*-\s*AliExpress(\s+\d+)?$', '', product_name).strip()
            product_name = re.sub(r'-AliExpress(\s+\d+)?$', '', product_name).strip()

        # Extraction de l'image
        img_tag = soup.find("img", {"class": lambda x: x and "magnifier--image" in x})
        if img_tag and img_tag.has_attr("src"):
            img_url = img_tag["src"]
        else:
            meta_img = soup.find("meta", property="og:image")
            if meta_img and meta_img.has_attr("content"):
                img_url = meta_img["content"]

        return product_name, img_url

    except Exception as e:
        print(f"[ERREUR] get_aliexpress_product_info: {str(e)}")
        return None, None


def get_product_details_by_id(product_id):
    """
    Construit l'URL à partir de l'ID produit et récupère les détails.
    """
    product_url = f"https://vi.aliexpress.com/item/{product_id}.html"
    print(f"URL construite : {product_url}")
    return get_aliexpress_product_info(product_url)


# Exemple de test
if __name__ == "__main__":
    test_id = "1005006521657260"
    name, image = get_product_details_by_id(test_id)
    print("Nom du produit:", name)
    print("Image:", image)
