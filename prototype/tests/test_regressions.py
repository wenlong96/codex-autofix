"""
Regression tests for the team-purchase service.

Each test asserts a piece of correct behaviour. Tests that currently fail
describe behaviour the service does not yet satisfy.

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
# Team savings
# ---------------------------------------------------------------------------

def test_team_savings_reflects_actual_member_count(client):
    """Displayed savings should match the number of members who have joined."""
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
        f"{data['total_savings']}"
    )


# ---------------------------------------------------------------------------
# Join validation
# ---------------------------------------------------------------------------

def test_join_team_rejects_negative_quantity(client):
    """A negative quantity should be rejected with a 400."""
    r = client.post("/api/teams", json={"product_id": 1, "user_id": "alice"})
    team_id = r.json()["team_id"]

    r = client.post(
        f"/api/teams/{team_id}/join",
        json={"user_id": "bob", "quantity": -1},
    )
    assert r.status_code == 400, (
        f"Expected 400 for negative quantity, got {r.status_code}"
    )


def test_join_team_rejects_zero_quantity(client):
    """A zero quantity should be rejected with a 400."""
    r = client.post("/api/teams", json={"product_id": 1, "user_id": "alice"})
    team_id = r.json()["team_id"]

    r = client.post(
        f"/api/teams/{team_id}/join",
        json={"user_id": "bob", "quantity": 0},
    )
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Self-join
# ---------------------------------------------------------------------------

def test_creator_cannot_join_own_team(client):
    """A team's creator should not be able to join their own team."""
    r = client.post("/api/teams", json={"product_id": 1, "user_id": "alice"})
    team_id = r.json()["team_id"]

    # Alice tries to join her own team
    r = client.post(
        f"/api/teams/{team_id}/join",
        json={"user_id": "alice", "quantity": 1},
    )
    assert r.status_code == 400, (
        f"Expected 400 for self-join, got {r.status_code}"
    )


# ---------------------------------------------------------------------------
# Promo codes
# ---------------------------------------------------------------------------

def test_promo_save10_reduces_total(client):
    """SAVE10 should reduce the order total by 10%, not just be acknowledged."""
    # Reference total without promo
    r = client.post(
        "/api/checkout",
        json={"user_id": "alice", "product_id": 1, "quantity": 1},
    )
    full_total = r.json()["total"]

    # Same checkout with SAVE10
    r = client.post(
        "/api/checkout",
        json={
            "user_id": "alice",
            "product_id": 1,
            "quantity": 1,
            "promo_code": "SAVE10",
        },
    )
    data = r.json()

    expected = round(full_total * 0.90, 2)
    assert data["promo_applied"] is True
    assert data["total"] == pytest.approx(expected, abs=0.02), (
        f"Expected SAVE10 to reduce total to {expected}, got {data['total']}"
    )


def test_unknown_promo_not_marked_applied(client):
    """An unknown promo code should not be reported as applied."""
    r = client.post(
        "/api/checkout",
        json={
            "user_id": "alice",
            "product_id": 1,
            "quantity": 1,
            "promo_code": "BOGUSCODE",
        },
    )
    assert r.json()["promo_applied"] is False


# ---------------------------------------------------------------------------
# Price consistency
# ---------------------------------------------------------------------------

def test_list_price_matches_checkout_price(client):
    """The price shown in the product list should match what checkout charges."""
    r = client.get("/api/products")
    products = r.json()
    p = next(x for x in products if x["id"] == 1)
    list_displayed = p.get("display_price", p["price"])

    r = client.post(
        "/api/checkout",
        json={"user_id": "alice", "product_id": 1, "quantity": 1},
    )
    paid = r.json()["total"]

    assert list_displayed == pytest.approx(paid, abs=0.02), (
        f"List shows {list_displayed} but checkout charges {paid}"
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
