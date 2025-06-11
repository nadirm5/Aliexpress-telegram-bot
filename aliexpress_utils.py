
import requests
from bs4 import BeautifulSoup


def get_aliexpress_product_info(product_url):
    """
    Extract product name from AliExpress without Selenium
    Args:
        product_url (str): AliExpress product page URL
    Returns:
        str: product name
    """
    product_name = None # Initialize product_name
    img_url = None # Initialize img_url
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        cookies = {"x-hng": "lang=en-US", "intl_locale": "en_US"}
        response = requests.get(product_url, headers=headers, cookies=cookies, timeout=15)
        if response.status_code != 200:
            print(f"Failed to load page: {response.status_code}")
            return None, None # Return None for both if page fails
        soup = BeautifulSoup(response.text, "html.parser")
        
        # Try finding the specific h1 tag first
        root_div = soup.find("div", id="root")
        if root_div:
            h1 = root_div.select_one("div > div:nth-of-type(1) > div > div:nth-of-type(1) > div:nth-of-type(1) > div:nth-of-type(2) > div:nth-of-type(4) > h1")
            if h1:
                product_name = h1.get_text(strip=True)

        # Fallback to og:title meta tag
        if not product_name:
            meta_title = soup.find("meta", property="og:title")
            if meta_title and meta_title.has_attr("content"):
                product_name = meta_title["content"]

        # Fallback to keywords meta tag
        if not product_name:
            meta_name = soup.find("meta", attrs={"name": "keywords"})
            if meta_name and meta_name.has_attr("content"):
                # Take the first keyword as a potential name
                product_name = meta_name["content"].split(",")[0].strip()

        # Fallback to h1 with data-pl attribute
        if not product_name:
            h1 = soup.find("h1", {"data-pl": "product-title"})
            if h1:
                product_name = h1.get_text(strip=True)

        # Fallback to h1 with specific class names
        if not product_name:
            h1 = soup.find("h1", {"class": lambda x: x and ("product-title-text" in x or "product-title" in x)})
            if h1:
                product_name = h1.get_text(strip=True)

        # Generic h1 fallback (last resort for name)
        if not product_name:
            h1 = soup.find("h1")
            if h1:
                product_name = h1.get_text(strip=True)

        # --- Image Extraction ---
        img_tag = soup.find("img", {"class": lambda x: x and "magnifier--image" in x})
        if img_tag and img_tag.has_attr("src"):
            img_url = img_tag["src"]
        else:
            # Fallback to og:image meta tag
            meta_img = soup.find("meta", property="og:image")
            if meta_img and meta_img.has_attr("content"):
                img_url = meta_img["content"]

        # --- Clean up Product Name ---
        if product_name:
            # Remove common AliExpress suffixes, potentially followed by numbers
            import re
            # Regex: " - AliExpress" optionally followed by space and digits, at the end of the string
            product_name = re.sub(r'\s*-\s*AliExpress(\s+\d+)?$', '', product_name).strip()
            # Also handle case without leading space before hyphen
            product_name = re.sub(r'-AliExpress(\s+\d+)?$', '', product_name).strip()


        return product_name, img_url
    except Exception as e:
        print(f"An error occurred in get_aliexpress_product_info: {str(e)}") # Added function name for clarity
        return None, None # Return None for both on error

def get_product_details_by_id(product_id):
    """
    Construit une URL vers un produit AliExpress avec les paramètres Coins.
    Args:
        product_id (str or int): L'ID du produit AliExpress.
    Returns:
        tuple: (product_name, img_url) ou (None, None) en cas d'échec.
    """
    # Générer le lien avec les paramètres coin
    product_url = f"product_url = f"https://m.aliexpress.com/p/coin-index/index.html?productIds={product_id}&channel=coin&sourceType=620"
    print(f"Constructed Coins URL: {product_url}")
    return get_aliexpress_product_info(product_url)
