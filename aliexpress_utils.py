import requests
from bs4 import BeautifulSoup

def get_aliexpress_product_info(product_url):
    """
    Extract product name, price and image URL from AliExpress.
    Args:
        product_url (str): AliExpress product page URL
    Returns:
        tuple: (product_name, img_url, final_price) or (None, None, None) if failed
    """
    product_name = None  # Initialize product_name
    img_url = None  # Initialize img_url
    final_price = None  # Initialize final_price

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        cookies = {"x-hng": "lang=en-US", "intl_locale": "en_US"}
        response = requests.get(product_url, headers=headers, cookies=cookies, timeout=15)
        if response.status_code != 200:
            print(f"Failed to load page: {response.status_code}")
            return None, None, None  # Return None for all if page fails
        soup = BeautifulSoup(response.text, "html.parser")

        # Extract product name
        root_div = soup.find("div", id="root")
        if root_div:
            h1 = root_div.select_one("div > div:nth-of-type(1) > div > div:nth-of-type(1) > div:nth-of-type(1) > div:nth-of-type(2) > div:nth-of-type(4) > h1")
            if h1:
                product_name = h1.get_text(strip=True)
        if not product_name:
            meta_title = soup.find("meta", property="og:title")
            if meta_title and meta_title.has_attr("content"):
                product_name = meta_title["content"]

        # Extract image URL
        img_tag = soup.find("img", {"class": lambda x: x and "magnifier--image" in x})
        if img_tag and img_tag.has_attr("src"):
            img_url = img_tag["src"]
        else:
            meta_img = soup.find("meta", property="og:image")
            if meta_img and meta_img.has_attr("content"):
                img_url = meta_img["content"]

        # --- Extract Price ---
        # Look for the price in the "Acheter" section or as a reduced price
        discounted_price_tag = soup.find("span", {"class": "product-price-now"})  # Often used for reduced price
        if discounted_price_tag:
            final_price = discounted_price_tag.get_text(strip=True)
        
        # If no discounted price, fallback to the price in the "Acheter" section
        if not final_price:
            buy_section_price_tag = soup.find("span", {"class": "product-price-value"})  # Another class for price in the buying section
            if buy_section_price_tag:
                final_price = buy_section_price_tag.get_text(strip=True)

        # If no reduced price is found, fallback to the original price
        if not final_price:
            normal_price_tag = soup.find("span", {"class": "product-price-original"})  # Normal price if discounted is not available
            if normal_price_tag:
                final_price = normal_price_tag.get_text(strip=True)

        return product_name, img_url, final_price

    except Exception as e:
        print(f"An error occurred: {str(e)}")
        return None, None, None  # Return None for all on error
