# Group Buy Prototype Test Case Suite

This file records the manual QA test case design for the finalized Group Buy prototype. The suite can be used to verify the ideal prototype, expose intentionally injected bugs, and validate autofix-agent repairs.

Assumption: Unless stated otherwise, start from a fresh app/server state.

## Test Case ID: TC-001

Title:
Product List Loads Correctly

Priority:
P0

Type:
Happy Path

Covers:
Product browsing

Preconditions:
App running

Test Data:
`/products`

Steps:
1. Open `/products`.
2. Inspect product cards.

Expected Result:
1. Products `p001` to `p004` are visible with names, prices, and detail links.

Validation Method:
UI

Notes:
Core product availability smoke test.

## Test Case ID: TC-002

Title:
Product Detail Loads Correctly

Priority:
P0

Type:
Happy Path

Covers:
Product detail page

Preconditions:
Product list is accessible

Test Data:
`p001`

Steps:
1. Open `/products/p001`.
2. Inspect title, normal price, group-buy price, required size.

Expected Result:
1. Product detail shows correct product info.
2. `Buy Now` and `Group Buy` actions are visible.

Validation Method:
UI

Notes:
Baseline for checkout flows.

## Test Case ID: TC-003

Title:
Normal Checkout Uses Original Price

Priority:
P0

Type:
Happy Path / Pricing

Covers:
Normal checkout pricing

Preconditions:
Fresh state

Test Data:
User `u001`, product `p001`, quantity `1`

Steps:
1. Open `/products/p001`.
2. Click `Buy Now`.
3. Review checkout summary.
4. Place order.

Expected Result:
1. Original unit price is `$29.99`.
2. Discount is `$0.00`.
3. Final price is `$29.99`.
4. Order status is `CONFIRMED`.

Validation Method:
UI + API

Notes:
Normal pricing baseline.

## Test Case ID: TC-004

Title:
Group Buy Button Navigates To Checkout Before Session Creation

Priority:
P0

Type:
Regression / Bug Coverage

Covers:
Group-buy entry flow; early session creation bug

Preconditions:
Fresh state

Test Data:
User `u001`, product `p001`

Steps:
1. Open `/products/p001`.
2. Click `Group Buy`.
3. Inspect URL and page.
4. Optionally call `/api/group-buys/p001-u001` before placing order.

Expected Result:
1. User lands on checkout with `purchaseType=GROUP_BUY&startGroupBuy=true`.
2. Group-buy page/link does not exist before order placement.

Validation Method:
UI + API

Notes:
Catches group-buy session created before checkout.

## Test Case ID: TC-005

Title:
Creator Checkout Creates Group Buy Link And Pending Order

Priority:
P0

Type:
Happy Path

Covers:
Start group buy after checkout

Preconditions:
Fresh state

Test Data:
User `u001`, product `p001`, quantity `1`

Steps:
1. Click `Group Buy` for `p001`.
2. Place order.
3. View order confirmation.
4. Open group-buy page.

Expected Result:
1. Order status is `PENDING_GROUP_BUY`.
2. Group-buy ID is `p001-u001`.
3. Creator is `u001`.
4. Participant count is `1`.
5. Status is `PENDING`.

Validation Method:
UI + API

Notes:
Core creator flow.

## Test Case ID: TC-006

Title:
Group Buy Checkout Shows Correct Price Breakdown

Priority:
P0

Type:
Pricing / Bug Coverage

Covers:
Checkout unit price, discount, final payable

Preconditions:
Fresh state

Test Data:
User `u001`, product `p001`, quantity `1`

Steps:
1. Open group-buy checkout for `p001`.
2. Inspect order summary.

Expected Result:
1. Original unit price is `$29.99`.
2. Discount is `-$10.00`.
3. Final payable is `$19.99`.

Validation Method:
UI

Notes:
Catches discounted-price-as-unit-price bug.

## Test Case ID: TC-007

Title:
Quantity Affects Price But Not Participant Count

Priority:
P0

Type:
Edge Case / Bug Coverage

Covers:
Quantity pricing and unique participant count

Preconditions:
Fresh state

Test Data:
User `u001`, product `p001`, quantity `3`

Steps:
1. Start group-buy checkout for `p001`.
2. Set quantity to `3`.
3. Place order.
4. Open group-buy page and order API.

Expected Result:
1. Discount is `-$30.00`.
2. Final price is `$59.97`.
3. Participant count is `1`, not `3`.
4. Status remains `PENDING`.

Validation Method:
UI + API

Notes:
Catches quantity-counted-as-participants and discount-total mismatch bugs.

## Test Case ID: TC-008

Title:
Invalid Checkout Quantity Is Rejected

Priority:
P0

Type:
Negative / Edge Case

Covers:
Quantity boundary validation

Preconditions:
Checkout page open

Test Data:
`abc`, `0`, `-1`, `2.5`, blank

Steps:
1. Enter each invalid value in quantity.
2. Attempt to place order.
3. Optionally call `POST /api/orders` with same values.

Expected Result:
1. UI shows quantity validation error.
2. `Place Order` is disabled or blocked.
3. API returns `INVALID_QUANTITY`.
4. No order is created.

Validation Method:
UI + API

Notes:
Covers boundary input bug.

## Test Case ID: TC-009

Title:
Duplicate Creator Cannot Create Another Active Group Buy Order

Priority:
P0

Type:
Regression / Bug Coverage

Covers:
Duplicate start idempotency

Preconditions:
`u001` already created active `p001-u001` group buy

Test Data:
User `u001`, product `p001`

Steps:
1. Return to `/products/p001`.
2. Click `Group Buy`.
3. Attempt checkout again.
4. Inspect orders/group-buy page.

Expected Result:
1. User is redirected to existing group-buy session.
2. No extra pending order is created for same creator/session.
3. Participant count remains `1`.

Validation Method:
UI + API

Notes:
Covers complex bug: duplicate creator checkout creates extra pending order.

## Test Case ID: TC-010

Title:
Multiple Creators Can Start Separate Group Buys For Same Product

Priority:
P0

Type:
Multi-user / Regression

Covers:
Deterministic link generation

Preconditions:
Fresh state

Test Data:
`u001`, `u002`, product `p001`

Steps:
1. As `u001`, start group buy for `p001`.
2. Switch to `u002`.
3. Start group buy for `p001`.
4. Compare links.

Expected Result:
1. Alice link is `/group-buy/p001-u001`.
2. Bob link is `/group-buy/p001-u002`.
3. Both sessions exist independently.

Validation Method:
UI + API

Notes:
Catches product-only link bug.

## Test Case ID: TC-011

Title:
User Joins Existing Group Buy Only After Checkout

Priority:
P0

Type:
Happy Path / Multi-user

Covers:
Join flow

Preconditions:
`p002-u001` exists and is `PENDING`

Test Data:
Creator `u001`, joiner `u002`, product `p002`

Steps:
1. As `u002`, open `/group-buy/p002-u001`.
2. Click `Join Group Buy`.
3. Before placing order, inspect participant count.
4. Place order.

Expected Result:
1. Participant count changes only after checkout succeeds.
2. Joiner order is `PENDING_GROUP_BUY`.
3. Group becomes `READY_TO_CHECKOUT` for required size `2`.

Validation Method:
UI + API

Notes:
Covers joining users must complete checkout before being counted.

## Test Case ID: TC-012

Title:
Same User Cannot Join Same Group Buy Twice

Priority:
P0

Type:
Negative

Covers:
Duplicate join prevention

Preconditions:
`u002` already joined `p002-u001`

Test Data:
User `u002`, group buy `p002-u001`

Steps:
1. As `u002`, revisit `/group-buy/p002-u001`.
2. Attempt to join again via UI or API.

Expected Result:
1. Join action is unavailable or API returns `USER_ALREADY_JOINED`.
2. No duplicate order/participant is created.

Validation Method:
UI + API

Notes:
Core participant uniqueness rule.

## Test Case ID: TC-013

Title:
Join Checkout Uses Group Buy Product As Source Of Truth

Priority:
P0

Type:
Regression / Bug Coverage

Covers:
Frontend-backend consistency for join checkout

Preconditions:
`p001-u001` exists

Test Data:
User `u002`, manipulated URL `/checkout?productId=p002&purchaseType=GROUP_BUY&groupBuyId=p001-u001`

Steps:
1. Switch to `u002`.
2. Open manipulated checkout URL.
3. Inspect product/pricing.
4. Place order.

Expected Result:
1. Checkout displays product `p001`, not `p002`.
2. Order is created for `p001` and attached to `p001-u001`.

Validation Method:
UI + API

Notes:
Covers complex bug: join checkout trusts URL product ID.

## Test Case ID: TC-014

Title:
Status Becomes READY_TO_CHECKOUT But Not SUCCESS Automatically

Priority:
P0

Type:
Status Transition

Covers:
Group-buy status model

Preconditions:
Fresh state

Test Data:
Product `p002`, creator `u001`, joiner `u002`

Steps:
1. `u001` starts `p002` group buy.
2. `u002` joins.
3. Open group-buy page.
4. Inspect related orders.

Expected Result:
1. Status is `READY_TO_CHECKOUT`.
2. Orders remain `PENDING_GROUP_BUY`.
3. Group is not `SUCCESS` yet.

Validation Method:
UI + API

Notes:
Catches premature success/auto-confirm bugs.

## Test Case ID: TC-015

Title:
READY_TO_CHECKOUT Status Is Consistent Across Pages

Priority:
P0

Type:
Regression / Bug Coverage

Covers:
Freshness and stale status

Preconditions:
`p002-u001` has reached `READY_TO_CHECKOUT`

Test Data:
Creator order page, joiner order page, group-buy page

Steps:
1. Open group-buy page.
2. Open creator order confirmation.
3. Open joiner order confirmation.
4. Refresh/revisit each page.

Expected Result:
1. All pages consistently show group-buy status `READY_TO_CHECKOUT`.
2. No page shows stale `PENDING`.

Validation Method:
UI + API

Notes:
Covers complex bug: stale order confirmation status.

## Test Case ID: TC-016

Title:
Creator Can Finalize Only When Ready

Priority:
P0

Type:
Happy Path / Permission

Covers:
Creator-only finalization

Preconditions:
`p002-u001` is `READY_TO_CHECKOUT`

Test Data:
Creator `u001`

Steps:
1. Switch to `u001`.
2. Open `/group-buy/p002-u001`.
3. Click `Finalize Group Buy`.

Expected Result:
1. Group status becomes `SUCCESS`.
2. All orders for `p002-u001` become `CONFIRMED`.

Validation Method:
UI + API

Notes:
Core finalization happy path.

## Test Case ID: TC-017

Title:
Non-Creator Cannot Finalize Group Buy

Priority:
P0

Type:
Negative / Bug Coverage

Covers:
Finalization permission

Preconditions:
`p002-u001` is `READY_TO_CHECKOUT`

Test Data:
Non-creator `u002`

Steps:
1. Switch to `u002`.
2. Open `/group-buy/p002-u001`.
3. Check UI.
4. Call finalize API as `u002`.

Expected Result:
1. Finalize button is not visible.
2. API returns `ONLY_CREATOR_CAN_FINALIZE`.
3. Group remains `READY_TO_CHECKOUT`.

Validation Method:
UI + API

Notes:
Catches non-creator finalize bug.

## Test Case ID: TC-018

Title:
Creator Cannot Finalize Before Required Size Is Reached

Priority:
P0

Type:
Negative

Covers:
Finalization size validation

Preconditions:
`p001-u001` has only creator participant; required size is `3`

Test Data:
Creator `u001`

Steps:
1. Open `/group-buy/p001-u001` as `u001`.
2. Check UI.
3. Call finalize API as `u001`.

Expected Result:
1. Finalize button is not visible.
2. API returns `GROUP_BUY_SIZE_NOT_REACHED`.
3. Status remains `PENDING`.

Validation Method:
UI + API

Notes:
Covers required-size rule.

## Test Case ID: TC-019

Title:
Finalization Confirms Only Orders In Same Group Buy

Priority:
P0

Type:
Regression / Bug Coverage

Covers:
Cross-session order isolation

Preconditions:
Two group buys exist for same product: `p001-u001` and `p001-u002`

Test Data:
Make only `p001-u001` ready, then finalize it

Steps:
1. Create `p001-u001`.
2. Create `p001-u002`.
3. Add participants until only `p001-u001` is ready.
4. Finalize `p001-u001`.
5. Inspect orders for `p001-u002`.

Expected Result:
1. Only orders with `groupBuyId=p001-u001` become `CONFIRMED`.
2. `p001-u002` orders remain `PENDING_GROUP_BUY`.

Validation Method:
API + UI

Notes:
Covers complex bug: finalize confirms same-product orders.

## Test Case ID: TC-020

Title:
Group Buy Link Is Stable Across Current Mock User Changes

Priority:
P1

Type:
Regression / Link Behavior

Covers:
Share link stability

Preconditions:
`p001-u001` exists

Test Data:
Switch between `u001`, `u002`, `u003`

Steps:
1. Open `/orders/{creatorOrderId}`.
2. Copy/view group-buy link.
3. Switch mock user.
4. Reopen order/group-buy page.

Expected Result:
1. Link remains `/group-buy/p001-u001`.
2. Link does not change based on selected mock user.

Validation Method:
UI

Notes:
Covers deterministic link behavior.

## Test Case ID: TC-021

Title:
Order Confirmation Displays Correct Group-Buy Price Breakdown And Link

Priority:
P1

Type:
Pricing / Link Validation

Covers:
Order confirmation correctness

Preconditions:
Group-buy order exists for `p001`

Test Data:
Product `p001`, quantity `1` or `3`

Steps:
1. Place group-buy order.
2. Open order confirmation.
3. Inspect product, order status, original unit price, discount, final paid price, group-buy link.

Expected Result:
1. Product is correct.
2. Status is `PENDING_GROUP_BUY`.
3. Unit price is original price.
4. Discount and final price match checkout.
5. Link points to created group buy.

Validation Method:
UI + API

Notes:
Covers pricing and share-link correctness.

## Test Case ID: TC-022

Title:
Invalid Product And Group-Buy Routes Show Clear Errors

Priority:
P1

Type:
Negative / Error Handling

Covers:
Not-found behavior

Preconditions:
App running

Test Data:
`/products/invalid-id`, `/group-buy/invalid-id`, `/api/orders/invalid-id`

Steps:
1. Open invalid product route.
2. Open invalid group-buy route.
3. Fetch invalid order API or route.

Expected Result:
1. Product shows product-not-found state.
2. Group-buy shows group-buy-not-found state.
3. Order API returns `ORDER_NOT_FOUND`.

Validation Method:
UI + API

Notes:
Core error handling.

## Test Case ID: TC-023

Title:
Successful Group Buy Allows Same Creator To Start New Session Later

Priority:
P1

Type:
Edge Case / Lifecycle

Covers:
New group buy after success

Preconditions:
`p002-u001` has been finalized successfully

Test Data:
Creator `u001`, product `p002`

Steps:
1. Finalize `p002-u001`.
2. Return to `/products/p002`.
3. Click `Group Buy`.
4. Place order.

Expected Result:
1. New group-buy session can be created after previous session is `SUCCESS`.
2. No active-session block occurs.

Validation Method:
UI + API

Notes:
Covers duplicate rule exception for `SUCCESS`.

## Test Case ID: TC-024

Title:
Group Buy Page Updates After Join And Refresh

Priority:
P1

Type:
Freshness / Regression

Covers:
Frontend state refresh

Preconditions:
`p001-u001` exists with one participant

Test Data:
Joiners `u002`, `u003`

Steps:
1. Open group-buy page as creator and note participant count.
2. Switch to `u002` and join.
3. Reopen/refresh group-buy page.
4. Switch to `u003` and join if needed.

Expected Result:
1. Participant count and status update after each checkout.
2. Refresh shows same correct state.
3. No stale participant/status display.

Validation Method:
UI + API

Notes:
Covers frontend freshness and status transition visibility.
