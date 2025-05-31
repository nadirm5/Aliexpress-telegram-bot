import requests
from bs4 import BeautifulSoup

def get_aliexpress_product_info(product_url, platform="android"):
    """
    Extract product name from AliExpress without Selenium
    Args:
        product_url (str): AliExpress product page URL
        platform (str): "android" or "ios" to set User-Agent header accordingly (default: "android")
    Returns:
        tuple: (product_name, img_url)
    """
    import requests
    from bs4 import BeautifulSoup
    
    product_name = None
    img_url = None
    try:
        # Exemple de headers pour Android et iOS dans un même dictionnaire
        headers = {
            "android": {
                "User-Agent": "AliExpressAndroid/8.129.3 (Linux; U; Android 10; en-US; Pixel 3 Build/QP1A.190711.020) AliApp(AliExpress/8.129.3) WindVane/8.6.0 1080X2160",
                "Accept-Language": "fr-FR,fr;q=0.9"
            },
            "ios": {
                "User-Agent": "AliExpressiOS/8.129.3 (iPhone; iOS 16; Scale/3.00) AliApp(AliExpress/8.129.3) WindVane/8.6.0",
                "Accept-Language": "fr-FR,fr;q=0.9"
            }
        }
        
        # Sélection des headers selon la plateforme
        current_headers = headers.get(platform.lower(), headers["android"])

        cookies = {"x-hng": "lang=en-US", "intl_locale": "fr_FR"}  # adapte la langue si tu veux

        response = requests.get(product_url, headers=current_headers, cookies=cookies, timeout=15)
        if response.status_code != 200:
            print(f"Failed to load page: {response.status_code}")
            return None, None
        
        soup = BeautifulSoup(response.text, "html.parser")
        
        # Extraction du nom du produit (exemple simplifié)
        h1 = soup.find("h1")
        if h1:
            product_name = h1.get_text(strip=True)
        
        # Extraction de l'image (exemple simplifié)
        img_tag = soup.find("img")
        if img_tag and img_tag.has_attr("src"):
            img_url = img_tag["src"]
        
        return product_name, img_url
    
    except Exception as e:
        print(f"An error occurred in get_aliexpress_product_info: {str(e)}")
        return None, None

        soup = BeautifulSoup(response.text, "html.parser")
        
        root_div = soup.find("div", id="root")
        if root_div:
            h1 = root_div.select_one("div > div:nth-of-type(1) > div > div:nth-of-type(1) > div:nth-of-type(1) > div:nth-of-type(2) > div:nth-of-type(4) > h1")
            if h1:
                product_name = h1.get_text(strip=True)

        if not product_name:
            meta_title = soup.find("meta", property="og:title")
            if meta_title and meta_title.has_attr("content"):
                product_name = meta_title["content"]

        if not product_name:
            meta_name = soup.find("meta", attrs={"name": "keywords"})
            if meta_name and meta_name.has_attr("content"):
                product_name = meta_name["content"].split(",")[0].strip()

        if not product_name:
            h1 = soup.find("h1", {"data-pl": "product-title"})
            if h1:
                product_name = h1.get_text(strip=True)

        if not product_name:
            h1 = soup.find("h1", {"class": lambda x: x and ("product-title-text" in x or "product-title" in x)})
            if h1:
                product_name = h1.get_text(strip=True)

        if not product_name:
            h1 = soup.find("h1")
            if h1:
                product_name = h1.get_text(strip=True)

        img_tag = soup.find("img", {"class": lambda x: x and "magnifier--image" in x})
        if img_tag and img_tag.has_attr("src"):
            img_url = img_tag["src"]
        else:
            meta_img = soup.find("meta", property="og:image")
            if meta_img and meta_img.has_attr("content"):
                img_url = meta_img["content"]

        if product_name:
            import re
            product_name = re.sub(r'\s*-\s*AliExpress(\s+\d+)?$', '', product_name).strip()
            product_name = re.sub(r'-AliExpress(\s+\d+)?$', '', product_name).strip()

        return product_name, img_url

    except Exception as e:
        print(f"An error occurred in get_aliexpress_product_info: {str(e)}")
        return None, None

def generate_affiliate_app_links(product_id, affiliate_id="xman-t"):
    """
    Génère uniquement les liens AliExpress pour ouvrir dans l'application (iOS et Android)
    """
    ios_link = f"aliexpress://product/{product_id}?aff_platform=portals-tool&aff_trace_key={affiliate_id}"
    android_link = (
        f"intent://product/{product_id}#Intent;"
        f"scheme=aliexpress;package=com.alibaba.aliexpresshd;S.aff_platform=portals-tool;"
        f"S.aff_trace_key={affiliate_id};end"
    )
    return {
        "ios": ios_link,
        "android": android_link,
    }

def get_product_details_by_id(product_id, affiliate_id="default"):
    """
    Récupère nom, image, et liens d'affiliation app (iOS + Android) du produit.
    """
    product_url = f"https://vi.aliexpress.com/item/{product_id}.html"
    print(f"Constructed URL: {product_url}")
    product_name, img_url = get_aliexpress_product_info(product_url)
    links = generate_affiliate_app_links(product_id, affiliate_id)
    return {
        "product_name": product_name,
        "image_url": img_url,
        "affiliate_app_links": links
    }

# Exemple d'utilisation
if __name__ == "__main__":
    product_id = "1005001234567890"  # Remplace par un vrai product_id
    details = get_product_details_by_id(product_id)
    print(details)
