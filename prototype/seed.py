"""Seed the prototype DB with sample products."""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "prototype.db"

PRODUCTS = [
    (1, "Wireless Earbuds Pro", 89.90, "Active noise cancelling, 24hr battery", "https://placehold.co/400x400/orange/white?text=Earbuds"),
    (2, "Insulated Water Bottle", 24.50, "Keeps drinks cold for 24hr, hot for 12hr", "https://placehold.co/400x400/blue/white?text=Bottle"),
    (3, "Ergonomic Mouse", 45.00, "Wireless, 6 buttons, USB-C rechargeable", "https://placehold.co/400x400/green/white?text=Mouse"),
    (4, "LED Desk Lamp", 38.90, "Dimmable, USB charging port, 3 colour modes", "https://placehold.co/400x400/purple/white?text=Lamp"),
    (5, "Travel Backpack 25L", 65.00, "Water-resistant, laptop sleeve, USB pass-through", "https://placehold.co/400x400/red/white?text=Backpack"),
    (6, "Bluetooth Speaker", 52.00, "IPX7 waterproof, 12hr playback, dual pairing", "https://placehold.co/400x400/teal/white?text=Speaker"),
]


def seed():
    DB_PATH.unlink(missing_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            price REAL NOT NULL,
            description TEXT,
            image_url TEXT
        );
    """)
    conn.executemany(
        "INSERT OR REPLACE INTO products (id, name, price, description, image_url) "
        "VALUES (?, ?, ?, ?, ?)",
        PRODUCTS,
    )
    conn.commit()
    conn.close()
    print(f"Seeded {len(PRODUCTS)} products into {DB_PATH}")


if __name__ == "__main__":
    seed()
