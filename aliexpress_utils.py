import requests
from bs4 import BeautifulSoup
import re
import json
from urllib.parse import urlparse, quote

def get_product_details(url):
    """Scrape product details from any AliExpress URL"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9"
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Extract product ID
        product_id = re.search(r'item/(\d+)\.html', url).group(1)
        
        # Extract product name
        name = soup.find('meta', property='og:title')['content'].split('|')[0].strip()
        name = re.sub(r'-\s*AliExpress.*$', '', name, flags=re.IGNORECASE).strip()
        
        # Extract image
        img_url = soup.find('meta', property='og:image')['content']
        
        return {
            'product_id': product_id,
            'name': name,
            'image': img_url,
            'url': url
        }
        
    except Exception as e:
        print(f"Error scraping product: {str(e)}")
        return None

def generate_coin_link(product_ids, main_product_id):
    """Generate Coin page link with specific product first"""
    base_url = "https://m.aliexpress.com/p/coin-index/index.html"
    params = {
        "productIds": f"{main_product_id},{','.join(product_ids)}",
        "aff_platform": "promotion",
        "sk": "coin_center",
        "aff_trace_key": "your_tracking_key"
    }
    return f"{base_url}?{urlencode(params)}"

def main():
    # 1. Get target product URL from user
    product_url = input("Enter AliExpress product URL: ").strip()
    
    # 2. Scrape product details
    product = get_product_details(product_url)
    if not product:
        print("Failed to get product details")
        return
    
    print(f"\nProduct Found:")
    print(f"Name: {product['name']}")
    print(f"ID: {product['product_id']}")
    print(f"Image: {product['image']}")
    
    # 3. Get related products (example)
    related_ids = ["10050012345678", "10050023456789"]  # Replace with actual related products
    
    # 4. Generate Coin link with target product first
    coin_link = generate_coin_link(related_ids, product['product_id'])
    
    print("\nGenerated Coin Link:")
    print(coin_link)

if __name__ == "__main__":
    main()
