"""
Team Purchase Prototype — Shopee-style "team up with 1 other person for 15% off"

This is the service that personas will navigate and that the self-healing
orchestrator will patch.

Planted bugs (see BUGS.md for details):
  1. Stale total in GET /api/teams/{team_id}     (state bug)
  2. Negative quantity in POST /api/teams/{team_id}/join  (validation bug)
  3. Self-join not blocked in POST /api/teams/{team_id}/join  (auth bug)
"""

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

DB_PATH = Path(__file__).parent / "prototype.db"
STATIC_DIR = Path(__file__).parent / "static"

TEAM_DISCOUNT = 0.15  # 15% off when team is complete (>= 2 members)


# ---------------------------------------------------------------------------
# DB
# ---------------------------------------------------------------------------

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
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                price REAL NOT NULL,
                description TEXT,
                image_url TEXT
            );
            CREATE TABLE IF NOT EXISTS teams (
                id TEXT PRIMARY KEY,
                product_id INTEGER NOT NULL,
                creator_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS team_members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                team_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 1,
                joined_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS orders (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                team_id TEXT,
                product_id INTEGER NOT NULL,
                quantity INTEGER NOT NULL,
                unit_price REAL NOT NULL,
                total REAL NOT NULL,
                created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp INTEGER NOT NULL,
                method TEXT NOT NULL,
                path TEXT NOT NULL,
                status_code INTEGER NOT NULL,
                duration_ms INTEGER NOT NULL,
                error_message TEXT,
                request_body TEXT
            );
        """)
        conn.commit()


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class CreateTeamRequest(BaseModel):
    product_id: int
    user_id: str


class JoinTeamRequest(BaseModel):
    user_id: str
    quantity: int = 1


class CheckoutRequest(BaseModel):
    user_id: str
    team_id: str | None = None
    product_id: int
    quantity: int = 1


# ---------------------------------------------------------------------------
# App + middleware
# ---------------------------------------------------------------------------

app = FastAPI(title="Team Purchase Prototype")


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.time()
    body_bytes = b""
    if request.method in ("POST", "PUT", "PATCH"):
        body_bytes = await request.body()

        async def receive():
            return {"type": "http.request", "body": body_bytes}

        request._receive = receive

    error_msg = None
    try:
        response = await call_next(request)
        status = response.status_code
    except Exception as e:
        status = 500
        error_msg = str(e)
        raise
    finally:
        duration_ms = int((time.time() - start) * 1000)
        try:
            with get_db() as conn:
                conn.execute(
                    "INSERT INTO logs (timestamp, method, path, status_code, "
                    "duration_ms, error_message, request_body) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        int(time.time()),
                        request.method,
                        str(request.url.path),
                        status,
                        duration_ms,
                        error_msg,
                        body_bytes.decode(errors="ignore") if body_bytes else None,
                    ),
                )
                conn.commit()
        except Exception:
            pass  # don't let logging break the response

    return response


# ---------------------------------------------------------------------------
# Product routes
# ---------------------------------------------------------------------------

@app.get("/api/products")
def list_products():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM products").fetchall()
        return [dict(r) for r in rows]


@app.get("/api/products/{product_id}")
def get_product(product_id: int):
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM products WHERE id = ?", (product_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "Product not found")
        return dict(row)


# ---------------------------------------------------------------------------
# Team routes
# ---------------------------------------------------------------------------

@app.post("/api/teams")
def create_team(req: CreateTeamRequest):
    team_id = str(uuid.uuid4())[:8]
    now = int(time.time())
    with get_db() as conn:
        # Verify product exists
        product = conn.execute(
            "SELECT * FROM products WHERE id = ?", (req.product_id,)
        ).fetchone()
        if not product:
            raise HTTPException(404, "Product not found")

        conn.execute(
            "INSERT INTO teams (id, product_id, creator_id, created_at) "
            "VALUES (?, ?, ?, ?)",
            (team_id, req.product_id, req.user_id, now),
        )
        # Creator auto-joins
        conn.execute(
            "INSERT INTO team_members (team_id, user_id, quantity, joined_at) "
            "VALUES (?, ?, 1, ?)",
            (team_id, req.user_id, now),
        )
        conn.commit()
        return {"team_id": team_id, "share_url": f"/team/{team_id}"}


@app.get("/api/teams/{team_id}")
def get_team(team_id: str):
    """
    PLANTED BUG #1 (stale total):
    The `total_savings` field below is computed from a hardcoded "expected"
    member count of 2 instead of the actual current member count. So if a
    member leaves (or the team has only 1 member), the displayed savings is
    still computed as if there were 2 members. A persona checking out solo
    after seeing this number gets the wrong impression of the discount.
    """
    with get_db() as conn:
        team = conn.execute(
            "SELECT * FROM teams WHERE id = ?", (team_id,)
        ).fetchone()
        if not team:
            raise HTTPException(404, "Team not found")

        members = conn.execute(
            "SELECT * FROM team_members WHERE team_id = ?", (team_id,)
        ).fetchall()
        product = conn.execute(
            "SELECT * FROM products WHERE id = ?", (team["product_id"],)
        ).fetchone()

        member_count = len(members)
        complete = member_count >= 2

        # BUG #1: total_savings uses hardcoded 2 instead of len(members)
        total_savings = product["price"] * TEAM_DISCOUNT * member_count

        return {
            "team": dict(team),
            "members": [dict(m) for m in members],
            "product": dict(product) if product else None,
            "complete": complete,
            "discount_pct": TEAM_DISCOUNT * 100,
            "total_savings": round(total_savings, 2),
            "member_count": member_count,
        }


@app.post("/api/teams/{team_id}/join")
def join_team(team_id: str, req: JoinTeamRequest):
    """
    PLANTED BUG #2 (negative quantity):
    No validation that req.quantity > 0. A persona/attacker can submit
    quantity = -1, which at checkout produces a negative total = refund.

    PLANTED BUG #3 (self-join):
    No check that req.user_id != team.creator_id. Creator can join their own
    team and trigger the "team complete" state without a second buyer.
    """
    now = int(time.time())
    with get_db() as conn:
        team = conn.execute(
            "SELECT * FROM teams WHERE id = ?", (team_id,)
        ).fetchone()
        if not team:
            raise HTTPException(404, "Team not found")
        if team["status"] != "open":
            raise HTTPException(400, "Team is closed")

        # BUG #2: no quantity validation here
        # BUG #3: no creator_id check here

        conn.execute(
            "INSERT INTO team_members (team_id, user_id, quantity, joined_at) "
            "VALUES (?, ?, ?, ?)",
            (team_id, req.user_id, req.quantity, now),
        )
        conn.commit()
        members = conn.execute(
            "SELECT * FROM team_members WHERE team_id = ?", (team_id,)
        ).fetchall()
        return {"success": True, "member_count": len(members)}


# ---------------------------------------------------------------------------
# Checkout
# ---------------------------------------------------------------------------

@app.post("/api/checkout")
def checkout(req: CheckoutRequest):
    now = int(time.time())
    with get_db() as conn:
        product = conn.execute(
            "SELECT * FROM products WHERE id = ?", (req.product_id,)
        ).fetchone()
        if not product:
            raise HTTPException(404, "Product not found")

        unit_price = product["price"]
        if req.team_id:
            team = conn.execute(
                "SELECT * FROM teams WHERE id = ?", (req.team_id,)
            ).fetchone()
            if not team:
                raise HTTPException(404, "Team not found")
            members = conn.execute(
                "SELECT * FROM team_members WHERE team_id = ?", (req.team_id,)
            ).fetchall()
            if len(members) >= 2:
                unit_price = unit_price * (1 - TEAM_DISCOUNT)

        # Note: negative quantity flows through here unguarded (bug #2 effect)
        total = unit_price * req.quantity
        order_id = str(uuid.uuid4())[:8]
        conn.execute(
            "INSERT INTO orders (id, user_id, team_id, product_id, quantity, "
            "unit_price, total, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                order_id,
                req.user_id,
                req.team_id,
                req.product_id,
                req.quantity,
                unit_price,
                total,
                now,
            ),
        )
        conn.commit()
        return {
            "order_id": order_id,
            "total": round(total, 2),
            "unit_price": round(unit_price, 2),
        }


# ---------------------------------------------------------------------------
# Logs / observability (orchestrator reads from here)
# ---------------------------------------------------------------------------

@app.get("/api/_logs/recent")
def recent_logs(limit: int = 50):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM logs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


@app.get("/api/_logs/errors")
def error_logs(limit: int = 20):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM logs WHERE status_code >= 400 "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Static frontend
# ---------------------------------------------------------------------------

@app.get("/")
def root():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/product/{product_id}")
def product_page(product_id: int):
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/team/{team_id}")
def team_page(team_id: str):
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/order/{order_id}")
def order_page(order_id: str):
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

@app.on_event("startup")
def startup():
    init_db()


if __name__ == "__main__":
    import uvicorn
    init_db()
    uvicorn.run(app, host="0.0.0.0", port=8000)
