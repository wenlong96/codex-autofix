"""
Regression tests for the intended group-buy behavior.

These tests describe the correct product behavior. The product-vision branch
keeps several of them failing on purpose so the agents have planted bugs to
find and Codex has concrete repair targets.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from main import app, init_db
from seed import seed


@pytest.fixture(autouse=True)
def fresh_db():
    seed()
    init_db()
    yield


@pytest.fixture
def client():
    return TestClient(app)


def create_group_order(
    client: TestClient,
    *,
    user_id: str = "u001",
    product_id: str = "p001",
    quantity: int = 1,
    group_buy_id: str | None = None,
    start_group_buy: bool = True,
):
    return client.post(
        "/api/orders",
        json={
            "user_id": user_id,
            "product_id": product_id,
            "purchase_type": "GROUP_BUY",
            "quantity": quantity,
            "group_buy_id": group_buy_id,
            "start_group_buy": start_group_buy,
        },
    )


def test_products_load(client):
    response = client.get("/api/products")
    assert response.status_code == 200
    products = response.json()
    assert len(products) == 4
    assert {p["id"] for p in products} == {"p001", "p002", "p003", "p004"}


def test_normal_checkout_confirms_immediately(client):
    response = client.post(
        "/api/orders",
        json={
            "user_id": "u001",
            "product_id": "p001",
            "purchase_type": "NORMAL",
            "quantity": 2,
        },
    )
    assert response.status_code == 200
    order = response.json()
    assert order["status"] == "CONFIRMED"
    assert order["final_price"] == pytest.approx(59.98, abs=0.01)


def test_quantity_counts_as_one_unique_participant(client):
    response = create_group_order(client, user_id="u001", product_id="p001", quantity=3)
    group_buy_id = response.json()["group_buy_id"]

    group = client.get(f"/api/group-buys/{group_buy_id}").json()

    assert group["participant_count"] == 1
    assert group["status"] == "PENDING"


def test_invalid_group_buy_quantity_is_rejected(client):
    response = create_group_order(client, quantity=0)
    assert response.status_code == 400

    response = create_group_order(client, quantity=-1)
    assert response.status_code == 400


def test_group_buy_discount_amount_scales_with_quantity(client):
    response = create_group_order(client, user_id="u001", product_id="p001", quantity=3)
    order = response.json()

    assert order["discount_amount"] == pytest.approx(30.00, abs=0.01)
    assert order["final_price"] == pytest.approx(59.97, abs=0.01)


def test_join_checkout_uses_group_buy_product_as_source_of_truth(client):
    creator_order = create_group_order(
        client,
        user_id="u001",
        product_id="p001",
        quantity=1,
    ).json()

    # Manipulated request claims product p002 while joining p001's group buy.
    response = create_group_order(
        client,
        user_id="u002",
        product_id="p002",
        quantity=1,
        group_buy_id=creator_order["group_buy_id"],
        start_group_buy=False,
    )
    assert response.status_code == 200
    order = response.json()
    assert order["product_id"] == "p001"


def test_non_creator_cannot_finalize_group_buy(client):
    order = create_group_order(
        client,
        user_id="u001",
        product_id="p002",
        quantity=1,
    ).json()
    group_buy_id = order["group_buy_id"]
    create_group_order(
        client,
        user_id="u002",
        product_id="p002",
        quantity=1,
        group_buy_id=group_buy_id,
        start_group_buy=False,
    )

    response = client.post(
        f"/api/group-buys/{group_buy_id}/finalize",
        json={"user_id": "u002"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "ONLY_CREATOR_CAN_FINALIZE"


def test_creator_cannot_finalize_before_required_size(client):
    order = create_group_order(
        client,
        user_id="u001",
        product_id="p001",
        quantity=1,
    ).json()

    response = client.post(
        f"/api/group-buys/{order['group_buy_id']}/finalize",
        json={"user_id": "u001"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "GROUP_BUY_SIZE_NOT_REACHED"
