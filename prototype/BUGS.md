# Product-Vision Branch Planted Bugs

These bugs are intentionally planted for the group-buy product-vision agents.
They are different from the main TeamBuy SG bugs.

## Bug 1 - Group Buy creates a session before checkout

Agent target: `gb_flow_persona`

Clicking `Group Buy` on a product detail page immediately calls
`POST /api/group-buys` and navigates to `/group-buy/{id}`. Correct behavior is
to go to checkout first and create the group-buy session only after order
placement.

Locations:
- `prototype/static/app.js`, `viewProduct()`
- `prototype/main.py`, `POST /api/group-buys`

Regression coverage:
- `TC-004` in `TEST_CASE_SUITE.md`

## Bug 2 - Group-buy price breakdown is misleading

Agent target: `gb_price_persona`

Group-buy checkout displays the discounted group-buy price as the original unit
price. It also shows a single-unit final payable even when quantity is greater
than one.

Locations:
- `prototype/static/app.js`, `viewCheckout()`
- `prototype/main.py`, `create_order()`

Regression coverage:
- `test_group_buy_discount_amount_scales_with_quantity`
- `TC-006`
- `TC-007`

## Bug 3 - Invalid checkout quantity is accepted

Agent target: `gb_contract_fuzzer`

The order endpoint stores zero and negative quantities instead of rejecting
them with a validation error.

Location:
- `prototype/main.py`, `create_order()`

Regression coverage:
- `test_invalid_group_buy_quantity_is_rejected`
- `TC-008`

## Bug 4 - Join checkout trusts URL product ID

Agent target: `gb_contract_fuzzer`

When `group_buy_id` is present, checkout should use the group-buy session's
product as the source of truth. The planted bug trusts the request/URL
`product_id`, so a manipulated checkout can attach the wrong product to an
existing group buy.

Locations:
- `prototype/static/app.js`, `viewCheckout()`
- `prototype/main.py`, `create_order()`

Regression coverage:
- `test_join_checkout_uses_group_buy_product_as_source_of_truth`
- `TC-013`

## Bug 5 - Non-creators and not-ready groups can finalize

Agent target: `gb_security_auth`

The finalization endpoint does not check that the caller is the creator and does
not check that the group has reached its required size.

Location:
- `prototype/main.py`, `finalize_group_buy()`

Regression coverage:
- `test_non_creator_cannot_finalize_group_buy`
- `test_creator_cannot_finalize_before_required_size`
- `TC-017`
- `TC-018`

## Bug 6 - Participant count uses quantity, not unique users

Agent target: `gb_data_integrity`

Participant count sums order quantities. A single creator order with quantity
`3` can make a three-person group appear ready.

Location:
- `prototype/main.py`, `_participant_count()`

Regression coverage:
- `test_quantity_counts_as_one_unique_participant`
- `TC-007`

## Why this set

The set gives every product-vision agent a concrete target:

- `gb_flow_persona`: early group creation and product-only group links.
- `gb_price_persona`: incorrect checkout and stored discount math.
- `gb_contract_fuzzer`: invalid quantities and source-of-truth tampering.
- `gb_security_auth`: missing finalization authorization.
- `gb_data_integrity`: quantity-based participant drift.
