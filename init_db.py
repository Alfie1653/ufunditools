import sqlite3


conn = sqlite3.connect("database.db")

cursor = conn.cursor()


cursor.execute("""
CREATE TABLE IF NOT EXISTS purchases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token TEXT UNIQUE,
    product_id TEXT,
    used INTEGER DEFAULT 0
)
""")


conn.commit()
conn.close()


print("Database created")

#TG User ID, username, downloaded_at
conn = sqlite3.connect("database.db")
cursor = conn.cursor()

cursor.execute("ALTER TABLE purchases ADD COLUMN telegram_user_id TEXT")
cursor.execute("ALTER TABLE purchases ADD COLUMN username TEXT")
cursor.execute("ALTER TABLE purchases ADD COLUMN downloaded_at TEXT")

conn.commit()
conn.close()

print("Database updated")

# Add expiry column to purchases table
conn = sqlite3.connect("database.db")
cursor = conn.cursor()

try:
    cursor.execute("ALTER TABLE purchases ADD COLUMN expires_at TEXT")
except:
    pass

conn.commit()
conn.close()

print("Expiry column ready")

# Add phone_number column to purchases table
conn = sqlite3.connect("database.db")
cursor = conn.cursor()

try:
    cursor.execute("ALTER TABLE purchases ADD COLUMN phone_number TEXT")
except:
    pass

conn.commit()
conn.close()

print("Purchases column ready")

# Add email column to purchases table
conn = sqlite3.connect("database.db")
cursor = conn.cursor()

try:
    cursor.execute("ALTER TABLE purchases ADD COLUMN email TEXT")
except:
    pass

conn.commit()
conn.close()

print("email column added to purchases table")

# Add invoice_id column to purchases table
conn = sqlite3.connect("database.db")
cursor = conn.cursor()

try:
    cursor.execute("ALTER TABLE purchases ADD COLUMN invoice_id TEXT")
except:
    pass

conn.commit()
conn.close()

print("invoice_id column added to purchases table")

#Add status column to purchases table
conn = sqlite3.connect("database.db")
cursor = conn.cursor()

try:
    cursor.execute("ALTER TABLE purchases ADD COLUMN status TEXT DEFAULT 'pending'")
except:
    pass

conn.commit()
conn.close()

print("status column added to purchases table")