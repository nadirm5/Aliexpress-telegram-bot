import requests
from bs4 import BeautifulSoup

def get_product_info(product_url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    cookies = {"x-hng": "lang=en-US", "intl_locale": "en_US"}
    response = requests.get(product_url, headers=headers, cookies=cookies)
    
    if response.status_code != 200:
        print(f"Failed to load page: {response.status_code}")
        return None
    
    soup = BeautifulSoup(response.text, "html.parser")
    
    # Extraire le nom du produit
    product_name = soup.find("h1", {"class": "product-title-text"})
    if product_name:
        product_name = product_name.get_text(strip=True)
    
    # Extraire le prix d'origine et le prix réduit
    original_price = soup.find("span", {"class": "product-price-value"})
    discount_price = soup.find("span", {"class": "price"}).get_text(strip=True)
    
    # Extraire la réduction (pourcentage)
    discount_percent = soup.find("span", {"class": "percent"})
    if discount_percent:
        discount_percent = discount_percent.get_text(strip=True)
    
    # Extraire l'URL de l'image
    img_url = soup.find("meta", property="og:image")
    if img_url:
        img_url = img_url.get("content")
    
    return {
        "product_name": product_name,
        "original_price": original_price.get_text(strip=True) if original_price else None,
        "discount_price": discount_price,
        "discount_percent": discount_percent,
        "img_url": img_url
    }

def generate_product_message(product_info):
    if not product_info:
        return "Informations produit non disponibles"
    
    message = f"""
✨⭐️ {product_info['product_name']} ⭐️✨

💰 السعر بدون تخفيض: {product_info['original_price']}
▫️ 💥 السعر بعد التخفيض: {product_info['discount_price']}
▫️ 📉 تم التوفير: {product_info['discount_percent']}% من السعر الأصلي

🔗 [رابط المنتج على علي اكسبريس](https://s.click.aliexpress.com/e/{product_info['product_name']})
"""
    return message

# Exemple d'URL de produit AliExpress
product_url = "https://www.aliexpress.com/item/1234567890"  # Remplacer par l'URL d'un produit réel
product_info = get_product_info(product_url)
product_message = generate_product_message(product_info)

# Afficher le message généré
print(product_message)
