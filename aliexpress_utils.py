import requests
from bs4 import BeautifulSoup

def get_aliexpress_product_info(product_url):
    """
    Extract product details (name, image, price) from AliExpress without Selenium.
    Args:
        product_url (str): AliExpress product page URL
    Returns:
        tuple: (product_name, img_url, price) or (None, None, None) if failed.
    """
    product_name = None
    img_url = None
    price = None
    
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        cookies = {"x-hng": "lang=en-US", "intl_locale": "en_US"}
        response = requests.get(product_url, headers=headers, cookies=cookies, timeout=15)
        
        if response.status_code != 200:
            print(f"Failed to load page: {response.status_code}")
            return None, None, None
        
        soup = BeautifulSoup(response.text, "html.parser")
        
        # --- Extract Product Name ---
        root_div = soup.find("div", id="root")
        if root_div:
            h1 = root_div.select_one("div > div:nth-of-type(1) > div > div:nth-of-type(1) > div:nth-of-type(1) > div:nth-of-type(2) > div:nth-of-type(4) > h1")
            if h1:
                product_name = h1.get_text(strip=True)
        
        # Fallback to meta title if product name is not found
        if not product_name:
            meta_title = soup.find("meta", property="og:title")
            if meta_title and meta_title.has_attr("content"):
                product_name = meta_title["content"]
        
        # --- Extract Image URL ---
        img_tag = soup.find("img", {"class": lambda x: x and "magnifier--image" in x})
        if img_tag and img_tag.has_attr("src"):
            img_url = img_tag["src"]
        else:
            # Fallback to og:image meta tag
            meta_img = soup.find("meta", property="og:image")
            if meta_img and meta_img.has_attr("content"):
                img_url = meta_img["content"]
        
        # --- Extract Price ---
        price_tag = soup.find("span", {"class": "product-price-value"})
        if price_tag:
            price = price_tag.get_text(strip=True)
        
        # Clean up the product name (remove AliExpress suffix)
        if product_name:
            import re
            product_name = re.sub(r'\s*-\s*AliExpress(\s+\d+)?$', '', product_name).strip()
            product_name = re.sub(r'-AliExpress(\s+\d+)?$', '', product_name).strip()

        return product_name, img_url, price
    
    except Exception as e:
        print(f"An error occurred in get_aliexpress_product_info: {str(e)}")
        return None, None, None

def get_product_details_by_id(product_id):
    """
    Constructs URL from product ID and fetches product details.
    Args:
        product_id (str or int): The AliExpress product ID.
    Returns:
        tuple: (product_name, img_url, price) or (None, None, None) if failed.
    """
    product_url = f"https://www.aliexpress.com/item/{product_id}.html"
    print(f"Constructed URL: {product_url}")
    return get_aliexpress_product_info(product_url)
