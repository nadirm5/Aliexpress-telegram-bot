from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import time

def get_coins_price(url):
    options = Options()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')

    driver = webdriver.Chrome(options=options)

    try:
        driver.get(url)
        time.sleep(5)

        # Récupère le prix (ajuste les sélecteurs selon le produit)
        price = driver.find_element("css selector", "span.product-price-value").text
        print("Prix normal :", price)

        try:
            coins_discount = driver.find_element("xpath", "//span[contains(text(),'Coins to save')]").text
            print("Réduction coins :", coins_discount)
        except:
            print("Pas de réduction coins affichée.")

    except Exception as e:
        print("Erreur :", e)
    finally:
        driver.quit()

# Exemple d'utilisation
get_coins_price("https://s.click.aliexpress.com/e/_oms0bBH")
