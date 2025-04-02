# AliExpress Affiliate Telegram Bot

A Python-based Telegram bot that automatically detects AliExpress product links in messages, fetches product details using the AliExpress Affiliate API, generates multiple types of affiliate links (Coin, Super Deals, etc.), and posts a formatted message with an image (if available) and links back into the chat.

[![GitHub](https://img.shields.io/badge/GitHub-ReizoZ-blue?style=flat-square&logo=github)](https://github.com/ReizoZ) [![Telegram](https://img.shields.io/badge/Telegram-AliBot-blue?style=flat-square&logo=telegram)](https://t.me/Alixpress_discount_bot)
<!-- Optional: Add a Telegram link badge if you have a public bot/channel -->
<!-- [![Telegram](https://img.shields.io/badge/Telegram-Bot%20Channel-blue?style=flat-square&logo=telegram)](https://t.me/YourBotOrChannelLink) -->

## Features

*   **Automatic Link Detection:** Monitors chats for AliExpress product URLs using regex.
*   **Product Details:** Fetches product title, main image, and sale price via the AliExpress Affiliate API.
*   **Multiple Affiliate Links:** Generates affiliate links for various AliExpress promotions:
    *   🪙 Coin Offers
    *   🔥 Super Deals
    *   ⏳ Limited Offers
    *   💰 Big Save
*   **Official API Integration:** Uses `aliexpress.affiliate.productdetail.get` and `aliexpress.affiliate.link.generate` API endpoints via the `iop` SDK.
*   **Telegram Integration:** Built using the `python-telegram-bot` library.
*   **Formatted Responses:** Sends product information as a photo with caption (if image exists) or a formatted text message using HTML.
*   **Caching:** Implements an async-safe, time-based cache (default: 7 days) for product details and generated links to minimize API calls and speed up responses.
*   **Asynchronous Processing:** Leverages `asyncio`, `python-telegram-bot`'s async nature, and `ThreadPoolExecutor` for non-blocking API calls.
*   **Configurable:** Easily configured using a `.env` file for API keys, bot token, and regional settings.
*   **Periodic Cache Cleanup:** Uses `python-telegram-bot`'s `JobQueue` to automatically clean expired cache items daily.
*   **Basic Logging:** Includes standard Python logging for monitoring bot activity and errors.
*   **Static Links:** Includes easily accessible static links in the response footer for promotions (Choice Day, Best Deals) and social/community links (GitHub, Discord, Telegram).

## Prerequisites

*   Python 3.8+
*   `pip` (Python package installer)
*   Git (for cloning the repository)
*   A **Telegram Bot Token** (Get one from [@BotFather](https://t.me/BotFather) on Telegram)
*   AliExpress Affiliate API Credentials:
    *   App Key
    *   App Secret
    *   An active Affiliate Tracking ID ([AliExpress Portal](https://portals.aliexpress.com/))
*   Access to a server or machine to run the bot 24/7.

## Setup & Installation

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/ReizoZ/Aliexpress-telegram-bot.git
    cd Aliexpress-telegram-bot
    ```

2.  **Create and activate a virtual environment (recommended):**
    ```bash
    # Linux/macOS
    python3 -m venv venv
    source venv/bin/activate

    # Windows
    python -m venv venv
    .\venv\Scripts\activate
    ```

3.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```
## Configuration

1.  **Create a `.env` file:**
    Copy the example environment file (if you have one) or create a new file named `.env`:
    ```bash
    # Example: cp .env.example .env
    # Or just create a new .env file
    ```

2.  **Edit the `.env` file** with your specific credentials and settings:
    ```dotenv
    # Telegram Bot Token from @BotFather
    TELEGRAM_BOT_TOKEN=YOUR_TELEGRAM_BOT_TOKEN_HERE

    # AliExpress Affiliate API Credentials
    ALIEXPRESS_APP_KEY=YOUR_ALIEXPRESS_APP_KEY
    ALIEXPRESS_APP_SECRET=YOUR_ALIEXPRESS_APP_SECRET
    ALIEXPRESS_TRACKING_ID=YOUR_ALIEXPRESS_TRACKING_ID # e.g., default

    # Regional Settings for Product Details API (Defaults shown if not set)
    TARGET_CURRENCY=USD # e.g., EUR, GBP, RUB, BRL, etc.
    TARGET_LANGUAGE=en # e.g., ES, FR, PT, RU, IT, PL, NL, etc.
    QUERY_COUNTRY=US # e.g., ES, FR, PT, RU, IT, PL, NL, GB, DE, BR, etc.

    ```
    *   Replace the placeholder values with your actual tokens and keys.
    *   Adjust `TARGET_CURRENCY`, `TARGET_LANGUAGE`, and `QUERY_COUNTRY` according to your target audience and API requirements.

## Running the Bot

1.  Ensure your virtual environment is activated (if you created one).
2.  Run the bot script (assuming your file is named `app.py`):
    ```bash
    python app.py
    ```

The bot should connect to Telegram, and you'll see log messages in your console indicating it's running and ready to process links.

To keep the bot running permanently, consider using tools like:
*   `screen` or `tmux`
*   A process manager like `systemd` (Linux) or `supervisor`
*   Docker (if a `Dockerfile` is set up)

## Usage

1.  Start a chat with your bot on Telegram or add it to a group.
2.  Send the `/start` command for a welcome message.
3.  Send any message containing one or more valid AliExpress product URLs (e.g., `https://www.aliexpress.com/item/1234567890.html`).
4.  The bot will show a "typing..." indicator.
5.  It will then fetch product details and generate the various affiliate links.
6.  Finally, it will send a message back to the chat, usually with the product image as a photo and the details/links in the caption (formatted using HTML). If no image is found, it sends a text message. If link generation fails, it will indicate the failure.

## Docker Deployment (Optional)

If you have a `Dockerfile` set up for this project:

1.  **Build the Docker image:**
    ```bash
    docker build -t aliexpress-telegram-bot .
    ```

2.  **Run the Docker container:**
    Make sure to pass the environment variables from your `.env` file. You can use the `--env-file` flag:
    ```bash
    docker run --env-file .env -d --name ali-telegram-bot aliexpress-telegram-bot
    ```
    *(The `-d` flag runs the container in detached mode.)*

Consult the documentation for your specific deployment platform if using something like CapRover or Kubernetes.

## Dependencies

Key Python libraries used:

*   `python-telegram-bot` - For Telegram Bot API interaction.
*   `python-dotenv` - For loading environment variables from `.env` file.
*   `aiohttp` / `httpx` - Asynchronous HTTP clients (used by `python-telegram-bot`).
*   `requests` (likely pulled in by `iop`) - Synchronous HTTP client (used within `ThreadPoolExecutor` for the `iop` SDK).
*   `iop` (Assumed package name) - Alibaba/AliExpress API SDK.

See `requirements.txt` for a full list.

## Contributing

Contributions, issues, and feature requests are welcome. Feel free to check the [issues page](https://github.com/ReizoZ/Aliexpress-telegram-bot.git/issues) if you want to contribute.

## Author

*   **RizoZ** - [GitHub](https://github.com/ReizoZ)

## License

This project is licensed under the MIT License - see the `LICENSE` file for details.
