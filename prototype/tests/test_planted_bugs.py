"""
Tests that demonstrate the planted bugs.

Each test pair: one shows the buggy behaviour (CURRENTLY PASSES because the
bug exists), one shows the desired behaviour (CURRENTLY FAILS — these are
what Codex will need to make pass after patching).

Run with:
    cd prototype && python -m pytest tests/ -v
"""

import pytest
from fastapi.testclient import TestClient

from main import app, init_db
from seed import seed


@pytest.fixture(autouse=True)
def fresh_db():
    seed()  # resets DB with sample products
    init_db()
    yield


@pytest.fixture
def client():
    return TestClient(app)


# ---------------------------------------------------------------------------
# BUG #1 — Stale total in GET /api/teams/{team_id}
# ---------------------------------------------------------------------------

def test_bug1_team_total_savings_should_reflect_actual_member_count(client):
    """
    Currently FAILS: total_savings is hardcoded as if 2 members joined.
    After fix: total_savings should reflect actual member count.
    """
    # Creator starts a team (1 member only)
    r = client.post("/api/teams", json={"product_id": 1, "user_id": "alice"})
    team_id = r.json()["team_id"]

    r = client.get(f"/api/teams/{team_id}")
    data = r.json()

    # With only 1 member, savings should be for 1 person, not 2
    product_price = 89.90
    expected = round(product_price * 0.15 * 1, 2)
    assert data["total_savings"] == expected, (
        f"Expected savings for 1 member ({expected}) but got "
        f"{data['total_savings']} — bug #1"
    )


# ---------------------------------------------------------------------------
# BUG #2 — Negative quantity accepted in /api/teams/{team_id}/join
# ---------------------------------------------------------------------------

def test_bug2_join_team_should_reject_negative_quantity(client):
    """
    Currently FAILS: API accepts quantity = -1.
    After fix: should return 400.
    """
    r = client.post("/api/teams", json={"product_id": 1, "user_id": "alice"})
    team_id = r.json()["team_id"]

    r = client.post(
        f"/api/teams/{team_id}/join",
        json={"user_id": "bob", "quantity": -1},
    )
    assert r.status_code == 400, (
        f"Expected 400 for negative quantity, got {r.status_code} — bug #2"
    )


def test_bug2_join_team_should_reject_zero_quantity(client):
    """Zero quantity is also nonsensical."""
    r = client.post("/api/teams", json={"product_id": 1, "user_id": "alice"})
    team_id = r.json()["team_id"]

    r = client.post(
        f"/api/teams/{team_id}/join",
        json={"user_id": "bob", "quantity": 0},
    )
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# BUG #3 — Creator can self-join their own team
# ---------------------------------------------------------------------------

def test_bug3_creator_cannot_join_own_team(client):
    """
    Currently FAILS: creator can join their own team and trigger "complete".
    After fix: should return 400 or similar.
    """
    r = client.post("/api/teams", json={"product_id": 1, "user_id": "alice"})
    team_id = r.json()["team_id"]

    # Alice tries to join her own team
    r = client.post(
        f"/api/teams/{team_id}/join",
        json={"user_id": "alice", "quantity": 1},
    )
    assert r.status_code == 400, (
        f"Expected 400 for self-join, got {r.status_code} — bug #3"
    )


# ---------------------------------------------------------------------------
# Sanity checks (these should always pass)
# ---------------------------------------------------------------------------

def test_list_products_returns_seeded_products(client):
    r = client.get("/api/products")
    assert r.status_code == 200
    products = r.json()
    assert len(products) >= 6
    assert any(p["name"] == "Wireless Earbuds Pro" for p in products)


def test_happy_path_team_purchase(client):
    # Alice creates team
    r = client.post("/api/teams", json={"product_id": 1, "user_id": "alice"})
    team_id = r.json()["team_id"]

    # Bob joins
    r = client.post(
        f"/api/teams/{team_id}/join",
        json={"user_id": "bob", "quantity": 1},
    )
    assert r.status_code == 200

    # Team should be complete
    r = client.get(f"/api/teams/{team_id}")
    assert r.json()["complete"] is True
    assert r.json()["member_count"] == 2

    # Bob checks out at team price
    r = client.post(
        "/api/checkout",
        json={
            "user_id": "bob",
            "team_id": team_id,
            "product_id": 1,
            "quantity": 1,
        },
    )
    assert r.status_code == 200
    # Team price for 89.90 with 15% off = 76.415
    assert r.json()["total"] == pytest.approx(76.41, abs=0.02)
