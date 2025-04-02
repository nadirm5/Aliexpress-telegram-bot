# AliExpress Affiliate Link Telegram Bot

A Telegram bot that automatically detects AliExpress product links in messages, fetches product details, generates various affiliate links (Coin, Super Deals, etc.) using the AliExpress Affiliate API, and replies with the formatted information including the product image, price, and affiliate links.

## Features

*   **Automatic Link Detection:** Monitors messages for valid AliExpress product URLs.
*   **Product ID Extraction:** Parses URLs to find the unique AliExpress product ID.
*   **AliExpress API Integration:** Fetches product details (title, price, main image, currency) via the official AliExpress Affiliate API (`aliexpress.affiliate.productdetail.get`).
*   **Affiliate Link Generation:** Creates multiple affiliate links for different AliExpress offers (Coin, Super Deals, Limited Offers, Big Save) using the `aliexpress.affiliate.link.generate` API call and your tracking ID.
*   **Caching:** Caches product details and generated affiliate links for 7 days to reduce API calls and improve response time.
*   **Asynchronous Processing:** Uses `asyncio` and `ThreadPoolExecutor` to handle multiple URLs and API calls efficiently without blocking the bot.
*   **Formatted Replies:** Sends clear replies on Telegram, including the product image (if available), title, price, and buttons/links for the generated affiliate offers.
*   **Configurable:** Settings like target currency, language, country, and API credentials are configured via environment variables.
*   **Scheduled Cache Cleanup:** Automatically removes expired cache entries daily.

## Setup and Installation

1.  **Clone the Repository:**
    ```bash
    git clone https://github.com/ReizoZ/Aliexpress-telegram-bot.git
    cd Aliexpress-telegram-bot
    ```

2.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

3.  **Configure Environment Variables:**
    *   Copy the example environment file:
        ```bash
        cp .env.example .env
        ```
    *   Edit the `.env` file with your actual credentials and settings. See the **Environment Variables** section below for details. You **must** provide your Telegram Bot Token and AliExpress API credentials.

## Running the Bot

Once the setup is complete, start the bot using:

```bash
python app.py