import requests
from bs4 import BeautifulSoup
import re
from urllib.parse import urlparse

def get_aliexpress_product_info(product_url):
    """
    Amélioration majeure du scraping AliExpress avec :
    - Meilleure détection des noms de produits
    - Extraction fiable des images
    - Gestion des erreurs renforcée
    - Nettoyage des résultats
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9"
    }
    
    try:
        # Validation de l'URL
        parsed = urlparse(product_url)
        if not parsed.scheme or not parsed.netloc:
            raise ValueError("URL invalide")
        
        response = requests.get(product_url, headers=headers, timeout=15)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 1. Extraction du nom du produit (méthodes prioritaires)
        name = None
        extraction_methods = [
            # Méthode 1: Balise meta optimisée
            lambda: soup.find('meta', {'property': 'og:title'}).get('content').split('|')[0].strip(),
            
            # Méthode 2: Structure DOM précise
            lambda: soup.select_one('h1[itemprop="name"]').text.strip(),
            
            # Méthode 3: Nouvelle structure AliExpress
            lambda: soup.select_one('div.product-title-text').text.strip(),
            
            # Méthode 4: Fallback générique
            lambda: soup.find('h1').text.strip() if soup.find('h1') else None
        ]
        
        for method in extraction_methods:
            try:
                name = method()
                if name:
                    break
            except:
                continue
        
        # Nettoyage final du nom
        if name:
            name = re.sub(r'-\s*AliExpress.*$', '', name, flags=re.IGNORECASE).strip()
            name = re.sub(r'\s+', ' ', name)
        
        # 2. Extraction de l'image (méthodes prioritaires)
        img_url = None
        img_methods = [
            # Méthode 1: Image principale
            lambda: soup.find('img', {'class': 'magnifier-image'}).get('src'),
            
            # Méthode 2: Meta og:image
            lambda: soup.find('meta', property='og:image').get('content'),
            
            # Méthode 3: Image dans gallery
            lambda: soup.find('div', class_='image-viewer').find('img').get('src') if soup.find('div', class_='image-viewer') else None
        ]
        
        for method in img_methods:
            try:
                img_url = method()
                if img_url:
                    # Correction des URLs relatives
                    if img_url.startswith('//'):
                        img_url = f'https:{img_url}'
                    elif img_url.startswith('/'):
                        img_url = f'https://{parsed.netloc}{img_url}'
                    break
            except:
                continue
        
        return name, img_url
    
    except requests.RequestException as e:
        print(f"Erreur réseau: {str(e)}")
    except Exception as e:
        print(f"Erreur de traitement: {str(e)}")
    
    return None, None

def get_product_details_by_id(product_id):
    """Version optimisée pour les IDs produit"""
    if not str(product_id).isdigit():
        raise ValueError("ID produit doit être numérique")
    
    url = f"https://www.aliexpress.com/item/{product_id}.html"
    print(f"Scraping: {url}")
    return get_aliexpress_product_info(url)
