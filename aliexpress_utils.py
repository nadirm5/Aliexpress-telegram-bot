import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
import time

def get_aliexpress_product_info(product_url):
    """
    Extract product name and price from AliExpress using Selenium
    Args:
        product_url (str): AliExpress product page URL
    Returns:
        tuple: (product_name, img_url, price)
    """
    product_name = None  # Initialize product_name
    img_url = None       # Initialize img_url
    price = None         # Initialize price
    
    options = Options()
    options.headless = True  # Run browser in headless mode (without UI)
    driver = webdriver.Chrome(options=options)
    
    try:
        # Load the page using Selenium
        driver.get(product_url)
        time.sleep(5)  # Wait for the page to load
        
        # --- Get product name ---
        soup = BeautifulSoup(driver.page_source, "html.parser")
        root_div = soup.find("div", id="root")
        if root_div:
            h1 = root_div.select_one("div > div:nth-of-type(1) > div > div:nth-of-type(1) > div:nth-of-type(1) > div:nth-of-type(2) > div:nth-of-type(4) > h1")
            if h1:
                product_name = h1.get_text(strip=True)

        if not product_name:
            meta_title = soup.find("meta", property="og:title")
            if meta_title and meta_title.has_attr("content"):
                product_name = meta_title["content"]
        
        # --- Get product image URL ---
        img_tag = soup.find("img", {"class": lambda x: x and "magnifier--image" in x})
        if img_tag and img_tag.has_attr("src"):
            img_url = img_tag["src"]
        else:
            meta_img = soup.find("meta", property="og:image")
            if meta_img and meta_img.has_attr("content"):
                img_url = meta_img["content"]

        # --- Get product price ---
        try:
            # Example of finding price, adjust the CSS selector accordingly
            price_element = driver.find_element(By.CSS_SELECTOR, '.product-price-value')  # Example CSS selector for the price
            price = price_element.text if price_element else None
        except Exception as e:
            print(f"Failed to extract price: {e}")
        
        # Clean up the product name (if necessary)
        if product_name:
            import re
            product_name = re.sub(r'\s*-\s*AliExpress(\s+\d+)?$', '', product_name).strip()

        return product_name, img_url, price

    except Exception as e:
        print(f"An error occurred in get_aliexpress_product_info: {str(e)}")
        return None, None, None
    finally:
        driver.quit()  # Make sure to close the browser after scraping

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

# Example usage
product_id = "1234567890"  # Replace with a real product ID
product_name, img_url, price = get_product_details_by_id(product_id)
print(f"Product Name: {product_name}, Image URL: {img_url}, Price: {price}")
