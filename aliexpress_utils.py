import requests
from bs4 import BeautifulSoup
import re

def get_aliexpress_product_info(product_url):
    product_name = None
    img_url = None
    final_price = None
    original_price = None
    discount_percentage = None

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        }
        cookies = {"x-hng": "lang=en-US", "intl_locale": "en_US"}
        response = requests.get(product_url, headers=headers, cookies=cookies, timeout=15)
        if response.status_code != 200:
            print(f"Failed to load page: {response.status_code}")
            return None, None, None, None, None

        soup = BeautifulSoup(response.text, "html.parser")

        # --- Product name extraction ---
        title_tag = soup.find("h1")
        if title_tag:
            product_name = title_tag.get_text(strip=True)
        else:
            meta_title = soup.find("meta", property="og:title")
            if meta_title and meta_title.get("content"):
                product_name = meta_title["content"]

        # --- Clean up name ---
        if product_name:
            product_name = re.sub(r'\s*-\s*AliExpress(\s+\d+)?$', '', product_name).strip()
            product_name = re.sub(r'-AliExpress(\s+\d+)?$', '', product_name).strip()

        # --- Image ---
        img_tag = soup.find("img", {"class": lambda x: x and "magnifier--image" in x})
        if img_tag and img_tag.has_attr("src"):
            img_url = img_tag["src"]
        else:
            meta_img = soup.find("meta", property="og:image")
            if meta_img and meta_img.has_attr("content"):
                img_url = meta_img["content"]

        # --- Price extraction ---
        # Final price (discounted)
        final_price_tag = soup.select_one('span.product-price-value')
        if final_price_tag:
            final_price = final_price_tag.get_text(strip=True).replace('$', '')

        # Original price
        original_price_tag = soup.select_one('span.product-price-original')
        if original_price_tag:
            original_price = original_price_tag.get_text(strip=True).replace('$', '')
        else:
            original_price = final_price  # fallback

        # Discount calculation
        if original_price and final_price and original_price != final_price:
            try:
                original = float(original_price)
                final = float(final_price)
                discount_percentage = round((original - final) / original * 100)
            except:
                discount_percentage = None

        return product_name, img_url, original_price, final_price, discount_percentage

    except Exception as e:
        print(f"An error occurred in get_aliexpress_product_info: {str(e)}")
        return None, None, None, None, None
