import requests
from bs4 import BeautifulSoup
import re

def extract_product_id(url):
    match = re.search(r'/item/(\d+)\.html', url)
    return match.group(1) if match else None

def check_bundle_deals_and_get_ids(product_id):
    bundle_url = (
        f"https://www.aliexpress.com/ssr/300000512/BundleDeals2"
        f"?productIds={product_id}&disableNav=YES&_immersiveMode=true"
    )
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        response = requests.get(bundle_url, headers=headers, timeout=10)
        if response.status_code != 200:
            print(f"Erreur HTTP: {response.status_code}")
            return False, []

        text = response.text

        # Recherche simple de tous les productId dans la page bundle via regex
        found_ids = re.findall(r'"productId":"(\d+)"', text)
        unique_ids = list(set(found_ids))

        # On vérifie que la liste contient au moins l'ID du produit principal
        if product_id in unique_ids:
            return True, unique_ids
        else:
            return False, []

    except Exception as e:
        print(f"Exception dans check_bundle_deals_and_get_ids: {e}")
        return False, []

def generate_bundle_deal_link(product_ids, tracking_id="default"):
    # Format attendu par la page bundle : ID:quelquechose séparé par une virgule
    # La valeur après le ':' est un code fixe souvent très grand (exemple pris d'un lien réel)
    ids_str = ",".join(f"{pid}:12000000000000000" for pid in product_ids)
    return (
        "https://www.aliexpress.com/ssr/300000512/BundleDeals2"
        "?businessCode=guide&pha_manifest=ssr&_immersiveMode=true&disableNav=YES"
        f"&homeProductIds={ids_str}"
        "&wh_pid=300000512/BundleDeals2&wh_ttid=adc&adc_strategy=snapshot"
        f"&aff_short_key={tracking_id}&afSmartRedirect=y"
    )

def prepare_message_from_url(product_url, tracking_id="default"):
    product_id = extract_product_id(product_url)
    if not product_id:
        return "❌ Impossible d'extraire l'ID produit depuis l'URL."

    # Ici tu dois utiliser ta fonction pour récupérer nom + image
    # Par exemple : name, img = get_aliexpress_product_info(product_url)
    name, img = "Nom du produit fictif", "https://exemple.com/image.jpg"  # Placeholder

    has_bundle, bundle_ids = check_bundle_deals_and_get_ids(product_id)

    bundle_link = generate_bundle_deal_link(bundle_ids, tracking_id) if has_bundle else None

    message = f"Produit: {name}\n"
    if img:
        message += f"Image: {img}\n"
    message += f"Lien produit: {product_url}\n"
    if bundle_link:
        message += f"Offre bundle: {bundle_link}\n"
    else:
        message += "Pas d'offre bundle disponible.\n"
    return message

# Test rapide
if __name__ == "__main__":
    test_url = "https://www.aliexpress.com/item/1005006994570544.html"
    print(prepare_message_from_url(test_url, tracking_id="default"))
