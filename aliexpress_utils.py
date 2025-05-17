import requests
from bs4 import BeautifulSoup
import re

def get_aliexpress_product_info(product_url):
    """
    Extract product name and image from AliExpress without Selenium
    Args:
        product_url (str): AliExpress product page URL
    Returns:
        tuple: (product_name, img_url)
    """
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
            print(f"Failed to load page: {response.status_code}")
            return None, None
        soup = BeautifulSoup(response.text, "html.parser")

        root_div = soup.find("div", id="root")
        if root_div:
            h1 = root_div.select_one("div > div:nth-of-type(1) > div > div:nth-of-type(1) > "
                                     "div:nth-of-type(1) > div:nth-of-type(2) > div:nth-of-type(4) > h1")
            if h1:
                product_name = h1.get_text(strip=True)

        if not product_name:
            meta_title = soup.find("meta", property="og:title")
            if meta_title and meta_title.has_attr("content"):
                product_name = meta_title["content"]

        if not product_name:
            meta_name = soup.find("meta", attrs={"name": "keywords"})
            if meta_name and meta_name.has_attr("content"):
                product_name = meta_name["content"].split(",")[0].strip()

        if not product_name:
            h1 = soup.find("h1", {"data-pl": "product-title"})
            if h1:
                product_name = h1.get_text(strip=True)

        if not product_name:
            h1 = soup.find("h1", {"class": lambda x: x and ("product-title-text" in x or "product-title" in x)})
            if h1:
                product_name = h1.get_text(strip=True)

        if not product_name:
            h1 = soup.find("h1")
            if h1:
                product_name = h1.get_text(strip=True)

        img_tag = soup.find("img", {"class": lambda x: x and "magnifier--image" in x})
        if img_tag and img_tag.has_attr("src"):
            img_url = img_tag["src"]
        else:
            meta_img = soup.find("meta", property="og:image")
            if meta_img and meta_img.has_attr("content"):
                img_url = meta_img["content"]

        if product_name:
            product_name = re.sub(r'\s*-\s*AliExpress(\s+\d+)?$', '', product_name).strip()
            product_name = re.sub(r'-AliExpress(\s+\d+)?$', '', product_name).strip()

        return product_name, img_url
    except Exception as e:
        print(f"An error occurred in get_aliexpress_product_info: {str(e)}")
        return None, None

def get_product_details_by_id(product_id):
    """
    Construct product URL by ID and fetch details
    """
    product_url = f"https://vi.aliexpress.com/item/{product_id}.html"
    print(f"Constructed URL: {product_url}")
    return get_aliexpress_product_info(product_url)

def check_bundle_deals(product_id):
    """
    Check if Bundle Deals are available for a given product ID
    """
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
            print("Bundle page not reachable.")
            return False

        # Vérification texte simple
        if "bundle deals" in response.text.lower() or "Bundle price" in response.text:
            return True

        # Vérifie certaines balises avec texte
        soup = BeautifulSoup(response.text, "html.parser")
        if soup.find_all("div", string=lambda s: s and "Bundle price" in s):
            return True

        return False
    except Exception as e:
        print(f"Erreur check_bundle_deals: {e}")
        return False

def generate_bundle_deal_link(product_id, tracking_id="default"):
    """
    Génère un lien bundle deal avec tracking_id
    """
    return (
        f"https://www.aliexpress.com/ssr/300000512/BundleDeals2"
        f"?productIds={product_id}&disableNav=YES&_immersiveMode=true"
        f"&aff_short_key={tracking_id}&afSmartRedirect=y"
    )

# Exemple d’utilisation
if __name__ == "__main__":
    product_id = "1005005706713011"
    name, img = get_product_details_by_id(product_id)
    has_bundle = check_bundle_deals(product_id)
    bundle_link = generate_bundle_deal_link(product_id) if has_bundle else None

    print("Nom du produit:", name or "Non trouvé")
    print("Image URL:", img or "Non trouvée")
    print("Bundle Deals disponibles:", has_bundle)
    print("Lien Bundle Deal:", bundle_link or "Aucun bundle disponible")
