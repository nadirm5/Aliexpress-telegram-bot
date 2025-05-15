import requests
from bs4 import BeautifulSoup
import re

def get_aliexpress_product_info(product_url):
    """
    Extract product info (name, image, price) from AliExpress without Selenium.
    Args:
        product_url (str): AliExpress product page URL
    Returns:
        dict: {'name': str or None, 'img_url': str or None, 'price': str or None}
    """
    try:
        headers = {
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/120.0.0.0 Safari/537.36")
        }
        cookies = {"x-hng": "lang=en-US", "intl_locale": "en_US"}
        response = requests.get(product_url, headers=headers, cookies=cookies, timeout=15)
        
        if response.status_code != 200:
            print(f"Failed to load page: HTTP {response.status_code}")
            return {'name': None, 'img_url': None, 'price': None}
        
        soup = BeautifulSoup(response.text, "html.parser")

        # Try multiple ways to get product name
        product_name = None
        # 1. og:title meta tag
        meta_title = soup.find("meta", property="og:title")
        if meta_title and meta_title.has_attr("content"):
            product_name = meta_title["content"]
        
        # 2. h1 tags with common classes or attributes
        if not product_name:
            h1_candidates = soup.find_all("h1")
            for h1 in h1_candidates:
                text = h1.get_text(strip=True)
                if text and len(text) > 5:
                    product_name = text
                    break

        # Clean product name from AliExpress suffix
        if product_name:
            product_name = re.sub(r'\s*-\s*AliExpress(\s+\d+)?$', '', product_name).strip()
            product_name = re.sub(r'-AliExpress(\s+\d+)?$', '', product_name).strip()

        # Extract main image URL
        img_url = None
        # Try class with "magnifier--image"
        img_tag = soup.find("img", {"class": lambda x: x and "magnifier--image" in x})
        if img_tag and img_tag.has_attr("src"):
            img_url = img_tag["src"]
        else:
            # fallback og:image
            meta_img = soup.find("meta", property="og:image")
            if meta_img and meta_img.has_attr("content"):
                img_url = meta_img["content"]

        # Extract price if possible
        price = None
        # Look for meta tag price
        meta_price = soup.find("meta", property="product:price:amount")
        if meta_price and meta_price.has_attr("content"):
            price = meta_price["content"]
        else:
            # fallback: try common price selectors
            price_selectors = [
                'span.product-price-value',
                'span#j-sku-price',
                'span.price-current',
                'span.product-price',
                'span.price'
            ]
            for selector in price_selectors:
                price_tag = soup.select_one(selector)
                if price_tag:
                    price_text = price_tag.get_text(strip=True)
                    if price_text:
                        price = price_text
                        break
        
        return {'name': product_name, 'img_url': img_url, 'price': price}

    except Exception as e:
        print(f"Error in get_aliexpress_product_info: {e}")
        return {'name': None, 'img_url': None, 'price': None}

def get_product_details_by_id(product_id, domain='www.aliexpress.com'):
    """
    Build product URL from ID and fetch details.
    Args:
        product_id (str|int): AliExpress product ID
        domain (str): domain to use (default: www.aliexpress.com)
    Returns:
        dict: product info dict
    """
    product_url = f"https://{domain}/item/{product_id}.html"
    print(f"Fetching product from URL: {product_url}")
    return get_aliexpress_product_info(product_url)

# Exemple d'utilisation
if __name__ == "__main__":
    product_id = "1005004040532389"  # Exemple d'ID produit
    info = get_product_details_by_id(product_id)
    print("Nom du produit :", info['name'])
    print("Image du produit :", info['img_url'])
    print("Prix du produit :", info['price'])
