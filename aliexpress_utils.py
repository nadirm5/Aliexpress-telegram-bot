from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
import time

def get_aliexpress_price(url):
    options = Options()
    options.add_argument('--headless')  # Ne pas afficher le navigateur
    options.add_argument('--disable-gpu')
    options.add_argument('--no-sandbox')
    driver = webdriver.Chrome(options=options)

    try:
        driver.get(url)
        time.sleep(8)  # Attendre que les prix chargent

        # Récupérer le prix réduit
        try:
            price = driver.find_element(By.CSS_SELECTOR, 'div.product-price-current span').text
        except:
            price = "Prix non trouvé"

        # Récupérer la livraison
        try:
            shipping = driver.find_element(By.XPATH, '//div[contains(text(),"Shipping") or contains(text(),"Livraison")]').text
        except:
            shipping = "Livraison non trouvée"

        print(f"Prix: {price}")
        print(f"Livraison: {shipping}")
        return price, shipping

    finally:
        driver.quit()

# Exemple
url = "https://s.click.aliexpress.com/e/_EvszySa"
get_aliexpress_price(url)
