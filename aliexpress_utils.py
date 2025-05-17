import requests
from bs4 import BeautifulSoup
import re
import json

def extract_product_id(url):
    match = re.search(r'/item/(\d+)\.html', url)
    return match.group(1) if match else None

def get_aliexpress_product_info(product_url):
    # Même code que précédemment (ou à copier)
    pass  # Simplification ici, réutilise ta fonction complète

def get_product_details_by_id(product_id):
    product_url = f"https://www.aliexpress.com/item/{product_id}.html"
    return get_aliexpress_product_info(product_url)

def check_bundle_deals_and_get_ids(product_id):
    """Vérifie la présence d'une offre bundle et retourne la liste des IDs"""
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
            print("Page bundle non accessible.")
            return False, []

        text = response.text

        # Tentative d'extraire JSON des données bundle à partir du HTML (ex: <script> ou balise spécifique)
        soup = BeautifulSoup(text, "html.parser")

        # Recherche d'un script contenant "window.__INITIAL_STATE__" ou similaire
        scripts = soup.find_all("script")
        json_data = None
        for script in scripts:
            if script.string and "window.__INITIAL_STATE__" in script.string:
                # Extraire JSON contenu
                match = re.search(r'window\.__INITIAL_STATE__\s*=\s*({.*});', script.string, re.DOTALL)
                if match:
                    json_str = match.group(1)
                    try:
                        json_data = json.loads(json_str)
                    except Exception as e:
                        print(f"Erreur parsing JSON: {e}")
                    break
        
        if not json_data:
            # Si on ne trouve pas dans les scripts, on peut tenter autre chose ou retourner False
            print("Données JSON bundle non trouvées dans la page.")
            return False, []

        # Parcours du JSON pour récupérer la liste des IDs produits dans le bundle
        bundle_items = []
        try:
            bundles = json_data.get("bundleDeals", {}).get("bundleItems", [])
            for bundle in bundles:
                # Chaque bundle est un dict avec une liste de produits
                for item in bundle.get("items", []):
                    pid = str(item.get("productId"))
                    if pid and pid not in bundle_items:
                        bundle_items.append(pid)
        except Exception as e:
            print(f"Erreur extraction bundle items: {e}")

        if bundle_items:
            return True, bundle_items

        # Sinon recherche alternative simple dans la page (par exemple via regex)
        found_ids = re.findall(r'productId":"(\d+)"', text)
        if found_ids:
            unique_ids = list(set(found_ids))
            return True, unique_ids

        return False, []

    except Exception as e:
        print(f"Erreur check_bundle_deals_and_get_ids: {e}")
        return False, []

def generate_bundle_deal_link(product_ids, tracking_id="default"):
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

    name, img = get_product_details_by_id(product_id)
    has_bundle, bundle_ids = check_bundle_deals_and_get_ids(product_id)

    bundle_link = generate_bundle_deal_link(bundle_ids, tracking_id) if has_bundle else None

    message = f"Produit: {name or 'Produit inconnu'}\n"
    if img:
        message += f"Image: {img}\n"
    message += f"Lien produit: {product_url}\n"
    if bundle_link:
        message += f"Offre bundle: {bundle_link}\n"
    else:
        message += "Pas d'offre bundle disponible.\n"
    return message

# Exemple d'appel (n'oublie pas de définir ou copier get_aliexpress_product_info)
if __name__ == "__main__":
    url = "https://www.aliexpress.com/item/1005006994570544.html"
    print(prepare_message_from_url(url, tracking_id="default"))
