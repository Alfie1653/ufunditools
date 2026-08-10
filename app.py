import os
import json
import secrets
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
import psycopg2
import psycopg2.extras
import hmac

load_dotenv()

app = Flask(__name__)
allowed_origins = os.environ["ALLOWED_ORIGINS"].split(",")
CORS(app, origins=allowed_origins)

limiter = Limiter (
    get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://",
)  # Use in-memory storage for rate limiting

with open("products.json") as file:
    products = json.load(file)

DATABASE_URL = os.environ["DATABASE_URL"]
INTASEND_TOKEN = os.environ["INTASEND_API_TOKEN"]
INTASEND_PUBLISHABLE_KEY = os.environ["INTASEND_PUBLISHABLE_KEY"]
INTASEND_WEBHOOK_CHALLENGE = os.environ["INTASEND_WEBHOOK_CHALLENGE"]
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_WEBHOOK_SECRET = os.environ["TELEGRAM_WEBHOOK_SECRET"]
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
ADMIN_TELEGRAM_CHAT_ID = os.environ["ADMIN_TELEGRAM_CHAT_ID"]

service = APIService(
    token=INTASEND_TOKEN,
    publishable_key=INTASEND_PUBLISHABLE_KEY,
    test=False,  # flip to False (or remove) when you go live
)

def get_db():
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS purchases (
            id SERIAL PRIMARY KEY,
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
    cur.close()
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

def is_valid_phone_number(phone_number):
    """Expects the normalized format the frontend sends: 254XXXXXXXXX"""
    return bool(re.match(r"^254[71]\d{8}$", phone_number))

def sanitize_text(value, max_length=1000):
    """Strip HTML tags and excess whitespace from free-text input."""
    if not value:
        return ""
    value = value.strip()
    value = re.sub(r"<[^>]*>", "", value)  # strip anything that looks like an HTML tag
    return value[:max_length]

@app.context_processor
def inject_current_year():
    return {'current_year': datetime.now().year}

@app.route("/")
def home():
    featured_ids = ["ebook5", "ebook9", "ebook7", "ebook4"]
    featured_products = {pid: products[pid] for pid in featured_ids if pid in products}
    return render_template("home.html", featured_products=featured_products)

@app.route("/products")
def products_page():
    return render_template("products.html", products=products)

@app.route("/about")
def about():
    return render_template("about.html")

@app.route("/faq")
def faq():
    return render_template("faq.html")

@app.route("/terms")
def terms():
    return render_template("terms.html")

@app.route("/privacy")
def privacy():
    return render_template("privacy.html")

@app.route("/refunds")
def refunds():
    return render_template("refunds.html")

@app.route("/robots.txt")
def robots():
    return app.send_static_file("robots.txt")

@app.route("/howto")
def how_to():
    return render_template("how_to.html")

@app.route("/telegram-webhook", methods=["POST"])
@limiter.limit("60 per minute")  # Limit to 60 requests per minute per IP
def telegram_webhook():

    incoming_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if not hmac.compare_digest(incoming_secret or "", TELEGRAM_WEBHOOK_SECRET):
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
        print("TELEGRAM: forwarding support message to admin")

        from_user = message.get("from", {})
        sender_username = from_user.get("username")
        sender_name = f"{from_user.get('first_name','')} {from_user.get('last_name','')}".strip()
        sender_id = from_user.get("id")

        contact_line = f"@{sender_username}" if sender_username else sender_name
        notification = (
            f"💬 Support message from {contact_line} (id: {sender_id}):\n\n{text}"
        )
        send_telegram_message(ADMIN_TELEGRAM_CHAT_ID, notification)

        send_telegram_message(chat_id, "Thanks! We've received your message and will get back to you shortly.")
        return jsonify({"ok": True})

    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        print("TELEGRAM: /start with no token")
        send_telegram_message(chat_id, "No download token found.")
        return jsonify({"ok": True})

    token = parts[1].strip()
    print("TELEGRAM: token received:", token)

    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT product_id, used, expires_at FROM purchases WHERE token = %s",
            (token,)
        )
        row = cur.fetchone()

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

        thank_you_message = (
            "Thanks for your purchase! 🎓\n\n"
            "Happy studying, and all the best.\n\n"
            "If these notes helped, tell a classmate about Ufundi Tools -- "
            "it genuinely helps us keep curating more units."
        )
        send_telegram_message(chat_id, thank_you_message)

        from_user = message.get("from", {})
        telegram_user_id = str(from_user.get("id", ""))
        username = from_user.get("username") or f"{from_user.get('first_name','')} {from_user.get('last_name','')}".strip()

        cur.execute(
            """
            UPDATE purchases
            SET used = 1, telegram_user_id = %s, username = %s, downloaded_at = %s
            WHERE token = %s
            """,
            (telegram_user_id, username, datetime.now().isoformat(), token)
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()

    return jsonify({"ok": True})

@app.errorhandler(429)
def ratelimit_handler(e):
    return jsonify({
        "status": "error",
        "message": "Rate limit exceeded. Please try again later."
    }), 429


@app.route("/support-message", methods=["POST"])
@limiter.limit("5 per minute")
def support_message():
    data = request.json or {}

    message = sanitize_text(data.get("message") or "").strip()
    contact = sanitize_text(data.get("contact") or "").strip()

    if not message:
        return jsonify({"status": "error", "message": "Please enter a message."}), 400
    if not contact:
        return jsonify({"status": "error", "message": "Please provide a phone number or Telegram username."}), 400
    if len(message) > 1000 or len(contact) > 200:
        return jsonify({"status": "error", "message": "That's too long -- please shorten it."}), 400

    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO support_messages (message, contact) VALUES (%s, %s)",
            (message, contact)
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()

    notification = f"🆘 New support message:\n\n{message}"
    if contact:
        notification += f"\n\nContact: {contact}"

    send_telegram_message(ADMIN_TELEGRAM_CHAT_ID, notification)

    return jsonify({"status": "ok", "message": "Thanks! We'll get back to you shortly."})


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
        try:
            cur = conn.cursor()
            cur.execute(
            """
            INSERT INTO purchases (token, product_id, phone_number, email, invoice_id, status, expires_at)
            VALUES (%s, %s, %s, %s, %s, 'pending', %s)
            """,
            (order_token, product_id, phone_number, email, invoice_id, expiry_time.isoformat()),
        )
            conn.commit()
        finally:
            cur.close()
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
            "message": "Something went wrong on the server. Please try again later."
        }), 500


@app.route("/order-status/<order_token>", methods=["GET"])
@limiter.limit("30 per minute")  # Limit to 30 requests per minute per IP
def order_status(order_token):
    """The frontend polls this after /buy, waiting for the webhook to mark
    the order paid. Once it's paid, this is what hands back the Telegram
    link -- not /buy.

    On the frontend's final poll attempt (?check=1), if the order is still
    pending, we directly ask IntaSend for the real status instead of just
    giving up -- this catches cases where the webhook was missed or delayed.
    """
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM purchases WHERE token = %s", (order_token,)
        )
        row = cur.fetchone()

        if not row:
            return jsonify({"status": "error", "message": "Order not found"}), 404

        # Only reconcile with IntaSend if still pending AND the frontend
        # flagged this as the final check -- avoids hammering IntaSend's
        # API on every 3-second poll.
        do_reconcile = request.args.get("check") == "1"

        if row["status"] == "pending" and do_reconcile and row["invoice_id"]:
            try:
                status_response = service.collect.status(invoice_id=row["invoice_id"])
                print("RECONCILE CHECK:", status_response)

                real_state = None
                if isinstance(status_response, dict):
                    real_state = status_response.get("invoice", {}).get("state")

                if real_state == "COMPLETE":
                    cur.execute(
                        "UPDATE purchases SET status = 'paid' WHERE token = %s",
                        (order_token,)
                    )
                    conn.commit()
                    row = dict(row)
                    row["status"] = "paid"
                    print("RECONCILE: order updated to paid via direct check")

                elif real_state == "FAILED":
                    cur.execute(
                        "UPDATE purchases SET status = 'failed' WHERE token = %s",
                        (order_token,)
                    )
                    conn.commit()
                    row = dict(row)
                    row["status"] = "failed"
                    print("RECONCILE: order updated to failed via direct check")

            except Exception as e:
                # If the reconciliation check itself fails (network issue,
                # IntaSend downtime), don't crash -- just fall through and
                # report whatever status we already have.
                print("RECONCILE CHECK ERROR:", str(e))

    finally:
        cur.close()
        conn.close()

    if row["status"] == "paid":
        telegram_link = "https://t.me/UfundiToolsBot?start=" + row["token"]
        return jsonify({"status": "paid", "telegram_link": telegram_link})

    return jsonify({"status": row["status"]})


@app.route("/webhook/intasend", methods=["POST"])
@limiter.limit("60 per minute")  # Limit to 60 requests per minute per IP
def intasend_webhook():

    data = request.get_json(force=True, silent=True) or {}

    # Reject anything that doesn't carry our shared secret challenge --
    # this is what proves the request actually came from IntaSend.
    if not hmac.compare_digest(data.get("challenge") or "", INTASEND_WEBHOOK_CHALLENGE):
        print("WEBHOOK REJECTED: bad or missing challenge")
        return jsonify({"status": "unauthorized"}), 401

    invoice_id = data.get("invoice_id")
    state = data.get("state")

    print("INVOICE:", invoice_id)
    print("STATE:", state)

    if state == "COMPLETE" and invoice_id:

        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE purchases
                SET status = 'paid'
                WHERE invoice_id = %s
                """,
                (invoice_id,)
            )

            conn.commit()
            print("ROWS UPDATED:", cur.rowcount)
        finally:
            cur.close()
            conn.close()

    return jsonify({"status": "received"})


@app.route("/recover-link", methods=["POST"])
@limiter.limit("5 per minute")
def recover_link():
    data = request.json or {}
    phone_number = (data.get("phone_number") or "").strip()

    if not is_valid_phone_number(phone_number):
        return jsonify({
            "status": "error",
            "message": "Enter a valid Kenyan phone number (e.g. 07XXXXXXXX)."
        }), 400

    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT token, expires_at, used
            FROM purchases
            WHERE phone_number = %s AND status = 'paid'
            ORDER BY id DESC
            LIMIT 1
            """,
            (phone_number,)
        )
        row = cur.fetchone()
    finally:
        cur.close()
        conn.close()

    if not row:
        return jsonify({
            "status": "error",
            "message": "No paid order found for that number."
        }), 404

    if row["used"] == 1:
        return jsonify({
            "status": "error",
            "message": "That order's file has already been delivered on Telegram."
        }), 400

    if row["expires_at"]:
        expiry_time = datetime.fromisoformat(row["expires_at"])
        if datetime.now() > expiry_time:
            return jsonify({
                "status": "error",
                "message": "That order's link has expired. Please contact us for help."
            }), 400

    telegram_link = "https://t.me/UfundiToolsBot?start=" + row["token"]
    return jsonify({"status": "ok", "telegram_link": telegram_link})


@app.route("/request-note", methods=["POST"])
@limiter.limit("5 per minute")
def request_note():
    data = request.json or {}

    topic = sanitize_text(data.get("topic") or "").strip()
    details = sanitize_text(data.get("details") or "").strip()
    contact = sanitize_text(data.get("contact") or "").strip()

    if not topic:
        return jsonify({"status": "error", "message": "Please tell us what topic you need."}), 400

    if len(topic) > 200 or len(details) > 1000 or len(contact) > 200:
        return jsonify({"status": "error", "message": "That's too long -- please shorten it."}), 400

    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO note_requests (topic, details, contact) VALUES (%s, %s, %s)",
            (topic, details, contact)
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()

    notification = f"📩 New note request:\n\nTopic: {topic}"
    if details:
        notification += f"\nDetails: {details}"
    if contact:
        notification += f"\nContact: {contact}"

    send_telegram_message(ADMIN_TELEGRAM_CHAT_ID, notification)

    return jsonify({"status": "ok", "message": "Thanks! We'll get to work on it and upload it once it's ready."})

if __name__ == "__main__":
    app.run(debug=False)