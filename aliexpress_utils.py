from telegram import Update, InputMediaPhoto
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from aliexpress_scraper import get_product_details_by_short_url  # Code d'avant dans un fichier séparé (voir + bas)

TOKEN = 'VOTRE_TOKEN_BOT'

# Commande /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bienvenue ! Envoie-moi un lien AliExpress (même raccourci) et je te montrerai les détails du produit.")

# Quand un utilisateur envoie un lien
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if "aliexpress.com" in text:
        await update.message.reply_text("Analyse du lien en cours...")
        name, img, price, store = get_product_details_by_short_url(text, translate=True)

        if name:
            message = f"**{name}**\n\n"
            if price:
                message += f"💰 *Prix :* {price}\n"
            if store:
                message += f"🏬 *Boutique :* {store}\n"
            message += f"\n🔗 [Voir le produit]({text})"

            if img:
                await update.message.reply_photo(photo=img, caption=message, parse_mode="Markdown")
            else:
                await update.message.reply_text(message, parse_mode="Markdown")
        else:
            await update.message.reply_text("Échec de récupération du produit.")
    else:
        await update.message.reply_text("Veuillez envoyer un lien AliExpress valide.")

# Lancer le bot
def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Bot lancé...")
    app.run_polling()

if __name__ == "__main__":
    main()
