import requests
from bs4 import BeautifulSoup
import re
import json

def get_aliexpress_product_info(product_url):
    """
    Extract product name, image, and discount price from AliExpress product page.
    """
    product_name = None
    img_url = None
    discount_price = ""

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        cookies = {"x-hng": "lang=en-US", "intl_locale": "en_US"}
        response = requests.get(product_url, headers=headers, cookies=cookies, timeout=15)
        if response.status_code != 200:
            print(f"Failed to load page: {response.status_code}")
            return None, None, ""

        soup = BeautifulSoup(response.text, "html.parser")

        # Extraction nom du produit
        root_div = soup.find("div", id="root")
        if root_div:
            h1 = root_div.select_one("div > div:nth-of-type(1) > div > div:nth-of-type(1) > div:nth-of-type(1) > div:nth-of-type(2) > div:nth-of-type(4) > h1")
            if h1:
                product_name = h1.get_text(strip=True)

        if not product_name:
            meta_title = soup.find("meta", property="og:title")
            if meta_title and meta_title.has_attr("content"):
                product_name = meta_title["content"]

        # Extraction image
        img_tag = soup.find("img", {"class": lambda x: x and "magnifier--image" in x})
        if img_tag and img_tag.has_attr("src"):
            img_url = img_tag["src"]
        else:
            meta_img = soup.find("meta", property="og:image")
            if meta_img and meta_img.has_attr("content"):
                img_url = meta_img["content"]

        # Nettoyage nom
        if product_name:
            product_name = re.sub(r'\s*-\s*AliExpress(\s+\d+)?$', '', product_name).strip()

        # Extraction prix réduit depuis script JSON
        script_tag = soup.find("script", text=re.compile("window.runParams = "))
        if script_tag:
            try:
                json_text = re.search(r'window.runParams = ({.*});', script_tag.string).group(1)
                data = json.loads(json_text)
                price_info = data.get("data", {}).get("priceModule", {})
                discount_price = price_info.get("formatedActivityPrice", "") or price_info.get("formatedPrice", "")
            except Exception as e:
                print(f"Erreur JSON prix : {e}")

        return product_name, img_url, discount_price

    except Exception as e:
        print(f"Error in get_aliexpress_product_info: {e}")
        return None, None, ""

def get_product_details_by_id(product_id):
    product_url = f"https://vi.aliexpress.com/item/{product_id}.html"
    return get_aliexpress_product_info(product_url)

def get_product_ids_from_bundle(bundle_url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        response = requests.get(bundle_url, headers=headers, timeout=15)
        if response.status_code != 200:
            print(f"Erreur chargement page bundle: {response.status_code}")
            return []

        soup = BeautifulSoup(response.text, "html.parser")

        product_ids = set()

        # Chercher tous les liens avec /item/<id>.html
        for a_tag in soup.find_all("a", href=True):
            match = re.search(r'/item/(\d+)\.html', a_tag['href'])
            if match:
                product_ids.add(match.group(1))

        return list(product_ids)

    except Exception as e:
        print(f"Erreur récupération IDs bundle: {e}")
        return []

if __name__ == "__main__":
    bundle_url = "https://www.aliexpress.com/ssr/300000512/BundleDeals2?disableNav=YES&pha_manifest=ssr&_immersiveMode=true&productIds=1005005706713011&_launchTID=7413021c-3458-43f8-95d3-ab6111934dc8&aff_fcid=75485d61d54048c3acf04a553cf50699-1747403194481-07402-_omZaJR5&aff_fsk=_omZaJR5&nr=n&wh_pid=300000512%2FBundleDeals2&wh_ttid=adc&adc_strategy=snapshot&aff_fcid=ad588a0e664c4b6f825cd116c3bacdbe-1747405904957-02713-_ooyqC0b&tt=CPS_NORMAL&aff_fsk=_ooyqC0b&aff_platform=portals-tool&sk=_ooyqC0b&aff_trace_key=ad588a0e664c4b6f825cd116c3bacdbe-1747405904957-02713-_ooyqC0b&terminal_id=ee1b022d55a74e729882e01c8c313c45"

    product_ids = get_product_ids_from_bundle(bundle_url)
    print(f"Found {len(product_ids)} product IDs:")

    for pid in product_ids[:3]:  # Limite à 3 produits pour test
        name, img, price = get_product_details_by_id(pid)
        print(f"ID: {pid}\nName: {name}\nPrice: {price}\nImage URL: {img}\n")
