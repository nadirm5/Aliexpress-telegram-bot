from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager
import time

def get_aliexpress_price(short_url):
    # Config Chrome en mode headless (sans interface)
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    
    driver = webdriver.Chrome(ChromeDriverManager().install(), options=options)
    
    try:
        # Charger le lien court, laisser suivre la redirection
        driver.get(short_url)
        time.sleep(5)  # attendre que la page charge bien (ajuste si besoin)
        
        # Essayer de trouver le prix (peut varier selon la page)
        price_selectors = [
            "span.product-price-value",  # prix
            "span.product-price-current", 
            "span.price-current",
            "div.product-price-current span",
        ]
        price = None
        for selector in price_selectors:
            elems = driver.find_elements(By.CSS_SELECTOR, selector)
            if elems:
                price = elems[0].text.strip()
                if price:
                    break
        
        # Essayer de récupérer la livraison
        shipping = None
        shipping_selectors = [
            "span.shipping-price", 
            "div.product-shipping span",
            "div.shipping-fee",
        ]
        for selector in shipping_selectors:
            elems = driver.find_elements(By.CSS_SELECTOR, selector)
            if elems:
                shipping = elems[0].text.strip()
                if shipping:
                    break
        
        print(f"Prix produit: {price if price else 'Non trouvé'}")
        print(f"Livraison: {shipping if shipping else 'Non trouvée'}")
    
    finally:
        driver.quit()

if __name__ == "__main__":
    # Remplace par ton lien court Aliexpress
    url = "https://s.click.aliexpress.com/e/_oF81HSW"
    get_aliexpress_price(url)
