import requests
from bs4 import BeautifulSoup
import re
import json

# Extraction ID produit depuis URL
def extract_product_id(url):
    match = re.search(r'/item/(\d+)\.html', url)
    return match.group(1) if match else None

# Exemple simple de récupération nom + image produit (à adapter selon besoin)
def get_aliexpress_product_info(product_url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        response = requests.get(product_url, headers=headers, timeout=10)
        if response.status_code != 200:
            return None, None
        soup = BeautifulSoup(response.text, "html.parser")

        # Titre produit
        title_tag = soup.find("h1", {"class": "product-title-text"})
        title = title_tag.text.strip() if title_tag else None

        # Image principale
        img_tag = soup.find("img", {"class": "magnifier-image"})
        img = img_tag["src"] if img_tag and img_tag.has_attr("src") else None

        return title, img
    except Exception as e:
        print(f"Erreur get_aliexpress_product_info: {e}")
        return None, None

# Vérifie la présence d'offre bundle et extrait IDs des produits
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
            print("Page bundle non accessible.")
            return False, []

        text = response.text
        soup = BeautifulSoup(text, "html.parser")
        scripts = soup.find_all("script")
        json_data = None
        for script in scripts:
            if script.string and "window.__INITIAL_STATE__" in script.string:
                match = re.search(r'window\.__INITIAL_STATE__\s*=\s*({.*});', script.string, re.DOTALL)
                if match:
                    try:
                        json_data = json.loads(match.group(1))
                    except Exception as e:
                        print(f"Erreur parsing JSON: {e}")
                    break

        if not json_data:
            print("Données JSON bundle non trouvées dans la page.")
            return False, []

        bundle_items = []
        try:
            bundles = json_data.get("bundleDeals", {}).get("bundleItems", [])
            for bundle in bundles:
                for item in bundle.get("items", []):
                    pid = str(item.get("productId"))
                    if pid and pid not in bundle_items:
                        bundle_items.append(pid)
        except Exception as e:
            print(f"Erreur extraction bundle items: {e}")

        if bundle_items:
            return True, bundle_items

        # Alternative fallback
        found_ids = re.findall(r'productId":"(\d+)"', text)
        if found_ids:
            unique_ids = list(set(found_ids))
            return True, unique_ids

        return False, []

    except Exception as e:
        print(f"Erreur check_bundle_deals_and_get_ids: {e}")
        return False, []

# Génère lien bundle avec IDs et tracking
def generate_bundle_deal_link(product_ids, tracking_id="default"):
    ids_str = ",".join(f"{pid}:12000000000000000" for pid in product_ids)
    return (
        "https://www.aliexpress.com/ssr/300000512/BundleDeals2"
        "?businessCode=guide&pha_manifest=ssr&_immersiveMode=true&disableNav=YES"
        f"&homeProductIds={ids_str}"
        "&wh_pid=300000512/BundleDeals2&wh_ttid=adc&adc_strategy=snapshot"
        f"&aff_short_key={tracking_id}&afSmartRedirect=y"
    )

# Prépare le message final pour l’utilisateur
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

# Wrapper get_product_details_by_id pour compatibilité
def get_product_details_by_id(product_id):
    product_url = f"https://www.aliexpress.com/item/{product_id}.html"
    return get_aliexpress_product_info(product_url)

# Test rapide
if __name__ == "__main__":
    test_url = "https://www.aliexpress.com/item/1005006994570544.html"
    print(prepare_message_from_url(test_url, tracking_id="default"))
