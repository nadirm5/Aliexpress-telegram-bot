import requests
from bs4 import BeautifulSoup
import re

def get_first_coin_product(coin_url):
    """
    Récupère le premier produit visible d'une page Coin AliExpress
    Args:
        coin_url (str): URL de la page Coin (peut être un lien raccourci)
    Returns:
        dict: Détails du produit ou message d'erreur
    """
    try:
        # Configuration des headers pour simuler un navigateur mobile
        headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; SM-G980F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.120 Mobile Safari/537.36",
            "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7"
        }

        # Suivre les redirections pour obtenir l'URL finale
        session = requests.Session()
        response = session.head(coin_url, headers=headers, allow_redirects=True)
        final_url = response.url

        # Vérifier qu'on a bien une page Coin
        if not ('alimama' in final_url or 'coin' in final_url.lower()):
            return {"error": "Le lien ne mène pas à une page Coin AliExpress"}

        # Récupérer le contenu de la page
        page_response = session.get(final_url, headers=headers)
        soup = BeautifulSoup(page_response.text, 'html.parser')

        # Nouvelle méthode pour détecter le premier produit - version mobile
        product_card = soup.find('div', {'class': re.compile(r'product-card|coin-product|item-card', re.I)})
        
        if not product_card:
            # Fallback pour la version desktop
            product_card = soup.find('div', {'class': re.compile(r'mainItem|item-box', re.I)})

        if product_card:
            # Extraire les informations
            product_data = {
                'title': extract_text(product_card, ['.title', 'h3', '.product-title']),
                'price': extract_text(product_card, ['.price', '.product-price']),
                'original_price': extract_text(product_card, ['.original-price', '.price--line-through']),
                'discount': extract_text(product_card, ['.discount', '.sale-tag']),
                'rating': extract_text(product_card, ['.rating', '.star-rate']),
                'sales': extract_text(product_card, ['.sales', '.sold']),
                'image': extract_attr(product_card, 'img', 'src', ['.image', 'img']),
                'badges': extract_badges(product_card),
                'url': extract_product_url(product_card)
            }
            
            # Nettoyer les données
            product_data = {k: clean_value(v) for k, v in product_data.items()}
            return product_data
        
        return {"error": "Aucun produit trouvé sur la page Coin"}
        
    except Exception as e:
        return {"error": f"Erreur: {str(e)}"}

# Fonctions utilitaires
def extract_text(element, selectors):
    """Extrait le texte d'un élément avec plusieurs sélecteurs possibles"""
    for selector in selectors:
        found = element.select_one(selector)
        if found and found.text.strip():
            return found.text.strip()
    return None

def extract_attr(element, tag, attr, selectors):
    """Extrait un attribut d'un élément"""
    for selector in selectors:
        found = element.select_one(selector)
        if found:
            img = found.find(tag)
            if img and img.has_attr(attr):
                return img[attr]
    return None

def extract_badges(element):
    """Extrait les badges du produit"""
    badges = element.select('.badge, .tag, .label')
    return [badge.text.strip() for badge in badges if badge.text.strip()]

def extract_product_url(element):
    """Extrait l'URL du produit"""
    link = element.find('a', href=True)
    if link:
        return 'https:' + link['href'] if link['href'].startswith('//') else link['href']
    return None

def clean_value(value):
    """Nettoie les valeurs extraites"""
    if isinstance(value, str):
        return re.sub(r'\s+', ' ', value).strip()
    return value

# Exemple d'utilisation
if __name__ == "__main__":
    coin_link = "https://s.click.aliexpress.com/e/_onIOkB6"
    product = get_first_coin_product(coin_link)
    
    print("=== PREMIER PRODUIT DE LA PAGE COIN ===")
    for key, value in product.items():
        print(f"{key.upper()}: {value}")
