from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.action_chains import ActionChains
import time

def get_product_details_with_selenium(product_url):
    # Initialiser Chrome avec options
    options = webdriver.ChromeOptions()
    options.add_argument("--headless")  # Mode sans tête (pas d'interface graphique)
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

    try:
        # Ouvrir la page du produit
        driver.get(product_url)
        time.sleep(3)  # Attendre que la page se charge

        # Trouver le bouton ou le lien à cliquer pour afficher les prix
        # (Remplacer avec le sélecteur correct du bouton de promotion)
        try:
            # Exemple de clic sur un bouton pour afficher les prix (ajuste le sélecteur CSS)
            promo_button = driver.find_element(By.CSS_SELECTOR, "button.promotion-button")  # Remplace par le sélecteur correct
            ActionChains(driver).move_to_element(promo_button).click().perform()
            time.sleep(3)  # Attendre que le contenu soit chargé
        except Exception as e:
            print(f"Erreur en cliquant sur le bouton de promotion : {e}")

        # Récupérer le nom du produit
        product_name = driver.find_element(By.CSS_SELECTOR, "h1.product-title-text").text

        # Récupérer le prix standard
        standard_price = driver.find_element(By.CSS_SELECTOR, "span.product-price-value").text

        # Récupérer le prix promotionnel (si disponible)
        try:
            discount_price = driver.find_element(By.CSS_SELECTOR, "span.product-price-now").text
        except:
            discount_price = None  # Si pas de prix promo, mettre None

        return product_name, standard_price, discount_price

    except Exception as e:
        print(f"Erreur : {e}")
    finally:
        driver.quit()

# Utilisation de la fonction avec un lien de produit spécifique
product_url = "https://www.aliexpress.com/item/123456789"
product_name, standard_price, discount_price = get_product_details_with_selenium(product_url)
print(product_name, standard_price, discount_price)
