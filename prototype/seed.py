"""Seed the group-buy prototype DB with sample products."""

from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "prototype.db"

PRODUCTS = [
    (
        "p001",
        "Everyday Tote Pack",
        29.99,
        19.99,
        3,
        "Lightweight daily bag with laptop sleeve",
        "https://placehold.co/480x360/orange/white?text=Tote",
    ),
    (
        "p002",
        "Wireless Earbuds Mini",
        49.99,
        39.99,
        2,
        "Compact earbuds with charging case",
        "https://placehold.co/480x360/blue/white?text=Earbuds",
    ),
    (
        "p003",
        "Desk Lamp Pro",
        39.99,
        29.99,
        2,
        "Dimmable LED lamp with USB-C charging",
        "https://placehold.co/480x360/green/white?text=Lamp",
    ),
    (
        "p004",
        "Insulated Bottle Duo",
        24.99,
        18.99,
        4,
        "Keeps drinks cold for 24 hours",
        "https://placehold.co/480x360/purple/white?text=Bottle",
    ),
]


def seed():
    DB_PATH.unlink(missing_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS products (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            normal_price REAL NOT NULL,
            group_buy_price REAL NOT NULL,
            required_group_size INTEGER NOT NULL,
            description TEXT,
            image_url TEXT
        );
        """
    )
    conn.executemany(
        """
        INSERT OR REPLACE INTO products (
            id, name, normal_price, group_buy_price, required_group_size,
            description, image_url
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        PRODUCTS,
    )
    conn.commit()
    conn.close()
    print(f"Seeded {len(PRODUCTS)} group-buy products into {DB_PATH}")


if __name__ == "__main__":
    seed()
