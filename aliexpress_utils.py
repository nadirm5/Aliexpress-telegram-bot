import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs

def get_ali_product_from_coin_link(short_url):
    """
    Extrait le premier produit d'une page Coin AliExpress à partir d'un lien raccourci
    """
    try:
        # Suivre la redirection pour obtenir l'URL finale
        session = requests.Session()
        response = session.head(short_url, allow_redirects=True)
        final_url = response.url
        
        # Vérifier si c'est bien une page Coin
        if 'alimama' in final_url or 'coin' in final_url.lower():
            # Obtenir le contenu de la page
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            page_response = session.get(final_url, headers=headers)
            
            # Analyser avec BeautifulSoup
            soup = BeautifulSoup(page_response.text, 'html.parser')
            
            # Trouver les produits (adaptez ce sélecteur selon la structure actuelle)
            products = soup.select('.coin-product-item')  # Ce sélecteur peut nécessiter ajustement
            
            if products:
                first_product = products[0]
                
                # Extraire les informations du produit
                product_data = {
                    'title': first_product.select_one('.product-title').get_text(strip=True) if first_product.select_one('.product-title') else 'Titre non trouvé',
                    'price': first_product.select_one('.product-price').get_text(strip=True) if first_product.select_one('.product-price') else 'Prix non trouvé',
                    'discount': first_product.select_one('.product-discount').get_text(strip=True) if first_product.select_one('.product-discount') else None,
                    'rating': first_product.select_one('.product-rating').get_text(strip=True) if first_product.select_one('.product-rating') else None,
                    'sales': first_product.select_one('.product-sales').get_text(strip=True) if first_product.select_one('.product-sales') else None,
                    'badges': [badge.get_text(strip=True) for badge in first_product.select('.product-badge')],
                    'url': 'https:' + first_product.select_one('a')['href'] if first_product.select_one('a') else None
                }
                
                return product_data
            else:
                return {"error": "Aucun produit trouvé sur la page Coin"}
        else:
            return {"error": "Le lien ne semble pas mener à une page Coin AliExpress"}
            
    except Exception as e:
        return {"error": f"Une erreur s'est produite: {str(e)}"}

# Exemple d'utilisation
if __name__ == "__main__":
    coin_link = "https://s.click.aliexpress.com/e/_onIOkB6"
    product_info = get_ali_product_from_coin_link(coin_link)
    print("Informations du produit:")
    for key, value in product_info.items():
        print(f"{key}: {value}")
