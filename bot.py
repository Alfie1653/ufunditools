import os
import dotenv
import sqlite3
import json
from datetime import datetime

from telegram.ext import (
    Application,
    MessageHandler,
    CommandHandler,
    filters,
)


# ==========================
# LOAD PRODUCTS
# ==========================

with open("products.json") as file:
    products = json.load(file)


# ==========================
# LOAD BOT TOKEN
# ==========================

dotenv.load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")


# ==========================
# USER CLICKS TELEGRAM LINK
# /start TOKEN
# ==========================

async def start(update, context):

    # 1. Check if token exists in Telegram start command
    if not context.args:
        await update.message.reply_text(
            "No download token found."
        )
        return


    token = context.args[0]

    print("Token received:")
    print(token)


    # ==========================
    # 2. CONNECT TO DATABASE
    # ==========================

    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()


    # Find purchase linked to token
    cursor.execute(
        """
        SELECT product_id, used, expires_at
        FROM purchases
        WHERE token = ?
        """,
        (token,)
    )

    purchase = cursor.fetchone()


    # ==========================
    # 3. CHECK TOKEN EXISTS
    # ==========================

    if not purchase:
        conn.close()

        await update.message.reply_text(
            "Invalid download link."
        )
        return


    product_id, used, expires_at = purchase


    # ==========================
    # 4. CHECK IF TOKEN WAS USED
    # ==========================

    if used == 1:
        conn.close()

        await update.message.reply_text(
            "This download link has already been used!"
        )
        return



    # ==========================
    # 5. CHECK TOKEN EXPIRY
    # ==========================

    if expires_at:

        expiry_time = datetime.fromisoformat(expires_at)

        if datetime.now() > expiry_time:

            conn.close()

            await update.message.reply_text(
                "⏳ This download link has expired."
            )
            return



    print("Product:")
    print(product_id)


    # ==========================
    # 6. GET PRODUCT FILE
    # ==========================

    product = products[product_id]

    file_id = product["telegram_file_id"]



    # ==========================
    # 7. GET TELEGRAM USER DETAILS
    # ==========================

    user = update.effective_user

    user_id = str(user.id)

    username = (
        user.username
        if user.username
        else f"{user.first_name} {user.last_name or ''}".strip()
    )


    # ==========================
    # 8. SEND FILE
    # ==========================

    await update.message.reply_document(
        document=file_id,
        caption=product["name"]
    )


    # ==========================
    # 9. MARK TOKEN AS USED
    # ONLY AFTER SUCCESSFUL DELIVERY
    # ==========================

    cursor.execute(
        """
        UPDATE purchases
        SET
            used = 1,
            telegram_user_id = ?,
            username = ?,
            downloaded_at = ?
        WHERE token = ?
        """,
        (
            user_id,
            username,
            datetime.now().isoformat(),
            token
        )
    )


    conn.commit()
    conn.close()

    print("Download completed successfully.")



# ==========================
# CHANNEL FILE ID LISTENER
# Used when uploading products
# ==========================

async def get_channel_file(update, context):

    print("Channel post received!")

    if update.channel_post.document:

        file_id = update.channel_post.document.file_id

        print("FILE ID:")
        print(file_id)

    else:
        print("No document found")



# ==========================
# START BOT
# ==========================

app = Application.builder().token(BOT_TOKEN).build()


app.add_handler(
    CommandHandler(
        "start",
        start
    )
)


app.add_handler(
    MessageHandler(
        filters.Document.ALL,
        get_channel_file
    )
)


print("Bot is running...")

app.run_polling()