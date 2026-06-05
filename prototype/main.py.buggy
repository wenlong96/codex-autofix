"""
Group-buy prototype with intentionally planted branch-specific bugs.

This branch is for product-vision/group-buy agents. The app is deliberately
small, but it exposes the group-buy lifecycle those agents reason about:
product browsing, checkout, group-buy status, orders, and creator finalization.
"""

from __future__ import annotations

import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

DB_PATH = Path(__file__).parent / "prototype.db"
STATIC_DIR = Path(__file__).parent / "static"


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
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
            CREATE TABLE IF NOT EXISTS group_buys (
                id TEXT PRIMARY KEY,
                product_id TEXT NOT NULL,
                creator_user_id TEXT NOT NULL,
                required_group_size INTEGER NOT NULL,
                status TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                finalized_at INTEGER
            );
            CREATE TABLE IF NOT EXISTS orders (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                product_id TEXT NOT NULL,
                purchase_type TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                original_unit_price REAL NOT NULL,
                group_buy_price REAL NOT NULL,
                discount_amount REAL NOT NULL,
                final_price REAL NOT NULL,
                status TEXT NOT NULL,
                group_buy_id TEXT,
                created_at INTEGER NOT NULL
            );
            """
        )
        conn.commit()


class CreateGroupBuyRequest(BaseModel):
    product_id: str
    user_id: str


class CreateOrderRequest(BaseModel):
    user_id: str
    product_id: str
    purchase_type: str = "NORMAL"
    quantity: int = 1
    group_buy_id: str | None = None
    start_group_buy: bool = False


class FinalizeGroupBuyRequest(BaseModel):
    user_id: str


app = FastAPI(title="Group Buy Product Vision Prototype")


def _now() -> int:
    return int(time.time())


def _product(conn: sqlite3.Connection, product_id: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM products WHERE id = ?",
        (product_id,),
    ).fetchone()
    if not row:
        raise HTTPException(404, "PRODUCT_NOT_FOUND")
    return row


def _group_buy_id(product_id: str, creator_user_id: str) -> str:
    # PLANTED FLOW BUG: the id ignores creator_user_id. Multiple creators
    # starting the same product collapse into one group-buy link.
    return product_id


def _participant_count(conn: sqlite3.Connection, group_buy_id: str) -> int:
    # PLANTED DATA BUG: counts quantity, not unique users.
    row = conn.execute(
        """
        SELECT COALESCE(SUM(quantity), 0) AS participant_count
        FROM orders
        WHERE group_buy_id = ?
          AND purchase_type = 'GROUP_BUY'
          AND status IN ('PENDING_GROUP_BUY', 'CONFIRMED')
        """,
        (group_buy_id,),
    ).fetchone()
    return int(row["participant_count"] or 0)


def _refresh_group_buy_status(conn: sqlite3.Connection, group_buy_id: str) -> None:
    group = conn.execute(
        "SELECT * FROM group_buys WHERE id = ?",
        (group_buy_id,),
    ).fetchone()
    if not group or group["status"] == "SUCCESS":
        return

    status = "READY_TO_CHECKOUT" if (
        _participant_count(conn, group_buy_id) >= group["required_group_size"]
    ) else "PENDING"
    conn.execute(
        "UPDATE group_buys SET status = ? WHERE id = ?",
        (status, group_buy_id),
    )


def _get_or_create_group_buy(
    conn: sqlite3.Connection,
    product_id: str,
    creator_user_id: str,
) -> sqlite3.Row:
    product = _product(conn, product_id)
    group_buy_id = _group_buy_id(product_id, creator_user_id)
    group = conn.execute(
        "SELECT * FROM group_buys WHERE id = ?",
        (group_buy_id,),
    ).fetchone()
    if group:
        return group

    conn.execute(
        """
        INSERT INTO group_buys (
            id, product_id, creator_user_id, required_group_size, status,
            created_at
        )
        VALUES (?, ?, ?, ?, 'PENDING', ?)
        """,
        (
            group_buy_id,
            product_id,
            creator_user_id,
            product["required_group_size"],
            _now(),
        ),
    )
    return conn.execute(
        "SELECT * FROM group_buys WHERE id = ?",
        (group_buy_id,),
    ).fetchone()


def _serialize_product(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "normal_price": row["normal_price"],
        "group_buy_price": row["group_buy_price"],
        "required_group_size": row["required_group_size"],
        "description": row["description"],
        "image_url": row["image_url"],
    }


def _serialize_group_buy(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    _refresh_group_buy_status(conn, row["id"])
    group = conn.execute(
        "SELECT * FROM group_buys WHERE id = ?",
        (row["id"],),
    ).fetchone()
    product = _product(conn, group["product_id"])
    orders = conn.execute(
        "SELECT * FROM orders WHERE group_buy_id = ? ORDER BY created_at, id",
        (group["id"],),
    ).fetchall()
    return {
        "id": group["id"],
        "product_id": group["product_id"],
        "creator_user_id": group["creator_user_id"],
        "required_group_size": group["required_group_size"],
        "status": group["status"],
        "participant_count": _participant_count(conn, group["id"]),
        "product": _serialize_product(product),
        "orders": [dict(order) for order in orders],
    }


def _serialize_order(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    out = dict(row)
    out["product"] = _serialize_product(_product(conn, row["product_id"]))
    if row["group_buy_id"]:
        group = conn.execute(
            "SELECT * FROM group_buys WHERE id = ?",
            (row["group_buy_id"],),
        ).fetchone()
        if group:
            out["group_buy"] = _serialize_group_buy(conn, group)
    return out


@app.get("/api/products")
def list_products():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM products ORDER BY id").fetchall()
        return [_serialize_product(row) for row in rows]


@app.get("/api/products/{product_id}")
def get_product(product_id: str):
    with get_db() as conn:
        return _serialize_product(_product(conn, product_id))


@app.post("/api/group-buys")
def create_group_buy(req: CreateGroupBuyRequest):
    with get_db() as conn:
        group = _get_or_create_group_buy(conn, req.product_id, req.user_id)
        conn.commit()
        return _serialize_group_buy(conn, group)


@app.get("/api/group-buys/{group_buy_id}")
def get_group_buy(group_buy_id: str):
    with get_db() as conn:
        group = conn.execute(
            "SELECT * FROM group_buys WHERE id = ?",
            (group_buy_id,),
        ).fetchone()
        if not group:
            raise HTTPException(404, "GROUP_BUY_NOT_FOUND")
        return _serialize_group_buy(conn, group)


@app.post("/api/orders")
def create_order(req: CreateOrderRequest):
    with get_db() as conn:
        # PLANTED CONTRACT BUG: quantity is not validated. Zero and negative
        # quantities can be stored.
        product = _product(conn, req.product_id)
        purchase_type = req.purchase_type.upper()
        group_buy_id = req.group_buy_id

        if purchase_type == "GROUP_BUY":
            if req.start_group_buy:
                group = _get_or_create_group_buy(conn, req.product_id, req.user_id)
                group_buy_id = group["id"]
            elif group_buy_id:
                group = conn.execute(
                    "SELECT * FROM group_buys WHERE id = ?",
                    (group_buy_id,),
                ).fetchone()
                if not group:
                    raise HTTPException(404, "GROUP_BUY_NOT_FOUND")
                # PLANTED CONTRACT BUG: trusts req.product_id from the URL/body
                # instead of deriving product_id from the group-buy session.
            else:
                raise HTTPException(400, "GROUP_BUY_REQUIRED")

        original_unit_price = product["normal_price"]
        group_buy_price = product["group_buy_price"]
        if purchase_type == "GROUP_BUY":
            unit_price = group_buy_price
            # PLANTED PRICING BUG: stores the one-unit discount, not the total
            # discount for the selected quantity.
            discount_amount = original_unit_price - group_buy_price
            final_price = group_buy_price * req.quantity
            status = "PENDING_GROUP_BUY"
        else:
            unit_price = original_unit_price
            discount_amount = 0.0
            final_price = unit_price * req.quantity
            status = "CONFIRMED"

        order_id = str(uuid.uuid4())[:8]
        conn.execute(
            """
            INSERT INTO orders (
                id, user_id, product_id, purchase_type, quantity,
                original_unit_price, group_buy_price, discount_amount,
                final_price, status, group_buy_id, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                order_id,
                req.user_id,
                req.product_id,
                purchase_type,
                req.quantity,
                original_unit_price,
                group_buy_price,
                discount_amount,
                final_price,
                status,
                group_buy_id,
                _now(),
            ),
        )
        if group_buy_id:
            _refresh_group_buy_status(conn, group_buy_id)
        conn.commit()
        order = conn.execute(
            "SELECT * FROM orders WHERE id = ?",
            (order_id,),
        ).fetchone()
        return _serialize_order(conn, order)


@app.get("/api/orders/{order_id}")
def get_order(order_id: str):
    with get_db() as conn:
        order = conn.execute(
            "SELECT * FROM orders WHERE id = ?",
            (order_id,),
        ).fetchone()
        if not order:
            raise HTTPException(404, "ORDER_NOT_FOUND")
        return _serialize_order(conn, order)


@app.post("/api/group-buys/{group_buy_id}/finalize")
def finalize_group_buy(group_buy_id: str, req: FinalizeGroupBuyRequest):
    with get_db() as conn:
        group = conn.execute(
            "SELECT * FROM group_buys WHERE id = ?",
            (group_buy_id,),
        ).fetchone()
        if not group:
            raise HTTPException(404, "GROUP_BUY_NOT_FOUND")

        # PLANTED SECURITY BUGS: no creator check and no required-size check.
        conn.execute(
            """
            UPDATE orders
            SET status = 'CONFIRMED'
            WHERE purchase_type = 'GROUP_BUY'
              AND product_id = ?
              AND status = 'PENDING_GROUP_BUY'
            """,
            (group["product_id"],),
        )
        conn.execute(
            "UPDATE group_buys SET status = 'SUCCESS', finalized_at = ? WHERE id = ?",
            (_now(), group_buy_id),
        )
        conn.commit()

        updated = conn.execute(
            "SELECT * FROM group_buys WHERE id = ?",
            (group_buy_id,),
        ).fetchone()
        return _serialize_group_buy(conn, updated)


@app.get("/")
def root():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/products")
def products_page():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/products/{product_id}")
def product_page(product_id: str):
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/checkout")
def checkout_page():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/group-buy/{group_buy_id}")
def group_buy_page(group_buy_id: str):
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/orders/{order_id}")
def order_page(order_id: str):
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.on_event("startup")
def startup():
    init_db()


if __name__ == "__main__":
    import uvicorn

    init_db()
    uvicorn.run(app, host="0.0.0.0", port=8000)
