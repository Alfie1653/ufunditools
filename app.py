import os
import json
import secrets
import sqlite3
from datetime import datetime, timedelta
from flask import render_template
from flask import Flask, request, jsonify
from flask_cors import CORS
from intasend import APIService
from dotenv import load_dotenv
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask import jsonify
import re
import requests

load_dotenv()

app = Flask(__name__)
allowed_origins = os.environ.get("ALLOWED_ORIGINS", "http://127.0.0.1:5000").split(",")
CORS(app, origins=allowed_origins)

limiter = Limiter (
    get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://",
)  # Use in-memory storage for rate limiting

with open("products.json") as file:
    products = json.load(file)

INTASEND_TOKEN = os.getenv("INTASEND_API_TOKEN")
INTASEND_API_KEY = os.getenv("INTASEND_API_KEY")
INTASEND_WEBHOOK_CHALLENGE = os.getenv("INTASEND_WEBHOOK_CHALLENGE")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET")
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

service = APIService(
    token=INTASEND_TOKEN,
    publishable_key=INTASEND_API_KEY,
    test=False,  # flip to False (or remove) when you go live
)

DB_PATH = "database.db"
sqlite3.connect(DB_PATH).execute("PRAGMA journal_mode=WAL")  # improves concurrency


def get_db():
    conn = sqlite3.connect(
        DB_PATH,
        timeout=10.0,
        check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS purchases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token TEXT UNIQUE,
            product_id TEXT,
            phone_number TEXT,
            email TEXT,
            invoice_id TEXT,
            status TEXT DEFAULT 'pending',
            expires_at TEXT,
            used INTEGER DEFAULT 0,
            telegram_user_id TEXT,
            username TEXT,
            downloaded_at TEXT
        )
    """)
    conn.commit()
    conn.close()


init_db()

def send_telegram_message(chat_id, text):
    requests.post(
        f"{TELEGRAM_API_URL}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": text
        }
    )

def send_telegram_file(chat_id, file_path, caption):
    requests.post(
        f"{TELEGRAM_API_URL}/sendDocument",
        json={
            "chat_id": chat_id,
            "document": file_path,
            "caption": caption,
        }
    )

def is_valid_phone_number(phone_number):
    """Expects the normalized format the frontend sends: 254XXXXXXXXX"""
    return bool(re.match(r"^254[71]\d{8}$", phone_number))

@app.route("/telegram-webhook", methods=["POST"])
def telegram_webhook():

    incoming_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if incoming_secret != TELEGRAM_WEBHOOK_SECRET:
        print("TELEGRAM WEBHOOK REJECTED: bad or missing secret token")
        return jsonify({"ok": False}), 401

    update = request.get_json(force=True, silent=True) or {}
    print("TELEGRAM UPDATE:", update)

    message = update.get("message")

    if not message or "text" not in message:
        print("TELEGRAM: no message/text in update, ignoring")
        return jsonify({"ok": True})

    chat_id = message["chat"]["id"]
    text = message["text"]

    if not text.startswith("/start"):
        print("TELEGRAM: not a /start command, ignoring")
        return jsonify({"ok": True})

    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        print("TELEGRAM: /start with no token")
        send_telegram_message(chat_id, "No download token found.")
        return jsonify({"ok": True})

    token = parts[1].strip()
    print("TELEGRAM: token received:", token)

    conn = get_db()
    row = conn.execute(
        "SELECT product_id, used, expires_at FROM purchases WHERE token = ?",
        (token,)
    ).fetchone()

    if not row:
        print("TELEGRAM: token not found in database:", token)
        conn.close()
        send_telegram_message(chat_id, "Invalid download link.")
        return jsonify({"ok": True})

    print("TELEGRAM: found row -- product_id:", row["product_id"], "used:", row["used"], "expires_at:", row["expires_at"])

    if row["used"] == 1:
        print("TELEGRAM: token already used")
        conn.close()
        send_telegram_message(chat_id, "This download link has already been used!")
        return jsonify({"ok": True})

    if row["expires_at"]:
        expiry_time = datetime.fromisoformat(row["expires_at"])
        if datetime.now() > expiry_time:
            print("TELEGRAM: token expired")
            conn.close()
            send_telegram_message(chat_id, "⏳ This download link has expired.")
            return jsonify({"ok": True})

    product = products[row["product_id"]]
    file_id = product["telegram_file_id"]

    print("TELEGRAM: sending document, file_id:", file_id)
    send_result = requests.post(f"{TELEGRAM_API_URL}/sendDocument", json={
        "chat_id": chat_id,
        "document": file_id,
        "caption": product["name"],
    })
    print("TELEGRAM SEND RESPONSE:", send_result.status_code, send_result.text)

    from_user = message.get("from", {})
    telegram_user_id = str(from_user.get("id", ""))
    username = from_user.get("username") or f"{from_user.get('first_name','')} {from_user.get('last_name','')}".strip()

    conn.execute(
        """
        UPDATE purchases
        SET used = 1, telegram_user_id = ?, username = ?, downloaded_at = ?
        WHERE token = ?
        """,
        (telegram_user_id, username, datetime.now().isoformat(), token)
    )
    conn.commit()
    conn.close()

    return jsonify({"ok": True})

@app.errorhandler(429)
def ratelimit_handler(e):
    return jsonify({
        "status": "error",
        "message": "Rate limit exceeded. Please try again later."
    }), 429

@app.route("/")
def index():

    with open("products.json") as file:
        products = json.load(file)

    return render_template("index.html", products=products)

@app.route("/buy", methods=["POST"])
@limiter.limit("5 per minute")  # Limit to 5 requests per minute per IP
def buy():
    try:
        data = request.json

        product_id = data.get("product")
        phone_number = data.get("phone_number")

        if product_id not in products:
            return jsonify({"status": "error", "message": "Product not found"})

        if not phone_number:
            return jsonify({
                "status": "error",
                "message": "Phone number is required to trigger payment"
            })
        if not is_valid_phone_number(phone_number):
            return jsonify({
                "status": "error",
                "message": "Invalid phone number format. Use 254XXXXXXXXX."
            })

        product = products[product_id]

        # IntaSend's STK push API expects an email field, but we're only
        # asking the buyer for their phone number -- this placeholder just
        # satisfies the API, it's never used to contact anyone.
        email = f"{phone_number}@ufunditools.co.ke"

        order_token = secrets.token_urlsafe(8)
        expiry_time = datetime.now() + timedelta(hours=24)

        # this is the actual payment trigger -- it sends the STK push
        # ("enter your M-Pesa PIN") to the buyer's phone
        stk_response = service.collect.mpesa_stk_push(
            phone_number=phone_number,
            email=email,
            amount=product["price"],
            narrative=product["name"],
        )

        # log the full response so we can see exactly what IntaSend returns
        print("STK RESPONSE:", stk_response)

        # safely extract invoice_id from the response
        # if IntaSend changes format or fails, this prevents a crash
        invoice_id = None
        if isinstance(stk_response, dict):
            invoice_id = stk_response.get("invoice", {}).get("invoice_id")

        # if we didn't get an invoice_id, something went wrong upstream
        # return JSON instead of crashing (prevents '<!doctype html>' error)
        if not invoice_id:
            return jsonify({
                "status": "error",
                "message": "Failed to initiate payment. Please try again."
            })

        conn = get_db()
        conn.execute(
            """
            INSERT INTO purchases (token, product_id, phone_number, email, invoice_id, status, expires_at)
            VALUES (?, ?, ?, ?, ?, 'pending', ?)
            """,
            (order_token, product_id, phone_number, email, invoice_id, expiry_time.isoformat()),
        )
        conn.commit()
        conn.close()

        # no telegram_link yet -- payment hasn't happened
        return jsonify({
            "status": "pending",
            "message": "Enter your M-Pesa PIN on your phone to complete payment.",
            "token": order_token,
        })

    except Exception as e:
        # this catches ANY backend crash and forces a JSON response
        # instead of Flask returning an HTML error page
        print("BUY ERROR:", str(e))

        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@app.route("/order-status/<order_token>", methods=["GET"])
@limiter.limit("30 per minute")  # Limit to 30 requests per minute per IP
def order_status(order_token):
    """The frontend polls this after /buy, waiting for the webhook to mark
    the order paid. Once it's paid, this is what hands back the Telegram
    link -- not /buy."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM purchases WHERE token = ?", (order_token,)
    ).fetchone()
    conn.close()

    if not row:
        return jsonify({"status": "error", "message": "Order not found"}), 404

    if row["status"] == "paid":
        telegram_link = "https://t.me/UfundiToolsBot?start=" + row["token"]
        return jsonify({"status": "paid", "telegram_link": telegram_link})

    return jsonify({"status": row["status"]})


@app.route("/webhook/intasend", methods=["POST"])
def intasend_webhook():

    data = request.get_json(force=True, silent=True) or {}

    # Reject anything that doesn't carry our shared secret challenge --
    # this is what proves the request actually came from IntaSend.
    if data.get("challenge") != INTASEND_WEBHOOK_CHALLENGE:
        print("WEBHOOK REJECTED: bad or missing challenge")
        return jsonify({"status": "unauthorized"}), 401

    invoice_id = data.get("invoice_id")
    state = data.get("state")

    print("INVOICE:", invoice_id)
    print("STATE:", state)

    if state == "COMPLETE" and invoice_id:

        conn = get_db()

        result = conn.execute(
            """
            UPDATE purchases
            SET status = 'paid'
            WHERE invoice_id = ?
            """,
            (invoice_id,)
        )

        conn.commit()

        print("ROWS UPDATED:", result.rowcount)

        conn.close()

    return jsonify({"status": "received"})


if __name__ == "__main__":
    app.run(debug=False)