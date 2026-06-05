# Group Buy Prototype Bug Proposals

This file records intentional bug candidates for group-buy autofix-agent testing.
The current product-vision branch plants a selected target subset in
`prototype/main.py` and `prototype/static/app.js`; the remaining candidates are
kept as backlog ideas for broader agent coverage.

## Initial Bug Set

### Bug 1: Group Buy Button Creates Session Before Checkout

Area: Frontend

Feature affected:
Product detail page group-buy entry flow.

Bug behavior:
Clicking `Group Buy` calls `POST /api/group-buys` or navigates directly to `/group-buy/...` instead of going to checkout first.

Expected correct behavior:
Clicking `Group Buy` should navigate to checkout with `purchaseType=GROUP_BUY&startGroupBuy=true`. The group-buy session/link should only be created after placing the order.

Suggested reproduction steps:
1. Open `/products`.
2. Open a product detail page.
3. Click `Group Buy`.
4. Observe that the app does not land on checkout first.

Suggested validation after fix:
1. Click `Group Buy`.
2. Confirm URL is `/checkout?productId=...&purchaseType=GROUP_BUY&startGroupBuy=true`.
3. Confirm no group-buy page/link exists until `Place Order`.

### Bug 2: Group-Buy Checkout Shows Discounted Price as Unit Price

Area: Frontend

Feature affected:
Checkout page order summary.

Bug behavior:
For group-buy checkout, the order summary shows `unitPrice` as the discounted group-buy price instead of the original product price.

Expected correct behavior:
The checkout summary should show original unit price, discount amount, and discounted final payable amount.

Suggested reproduction steps:
1. Open a product with normal price `$29.99` and group-buy price `$19.99`.
2. Click `Group Buy`.
3. On checkout, inspect the order summary.
4. Observe original unit price incorrectly shows `$19.99`.

Suggested validation after fix:
1. Open the same group-buy checkout.
2. Confirm original unit price is `$29.99`.
3. Confirm discount is `-$10.00`.
4. Confirm final payable is `$19.99`.

### Bug 3: Participant Count Uses Quantity Instead Of Unique Users

Area: Backend

Feature affected:
Group-buy participant counting and status progression.

Bug behavior:
When a user places a group-buy order with quantity greater than 1, the participant count increases by quantity instead of counting the user once.

Expected correct behavior:
Each unique user should count as one participant per group-buy session, regardless of quantity purchased.

Suggested reproduction steps:
1. Start a group buy for a product requiring 3 participants.
2. Place the creator order with quantity `3`.
3. Open the group-buy page.
4. Observe participant count becomes `3` or status becomes `READY_TO_CHECKOUT`.

Suggested validation after fix:
1. Repeat with quantity `3`.
2. Confirm participant count is `1`.
3. Confirm status remains `PENDING` until enough unique users join.

### Bug 4: Non-Creator Can Finalize Group Buy

Area: Backend

Feature affected:
Creator-only finalization.

Bug behavior:
Any participant can call the finalize endpoint once the group reaches required size, even if they are not the creator.

Expected correct behavior:
Only `creatorUserId` can finalize. Non-creators should receive `ONLY_CREATOR_CAN_FINALIZE`.

Suggested reproduction steps:
1. User `u001` starts a group buy.
2. Other users join until status is `READY_TO_CHECKOUT`.
3. Call `POST /api/group-buys/{id}/finalize` as `u002`.
4. Observe the group becomes `SUCCESS`.

Suggested validation after fix:
1. Repeat the same request as `u002`.
2. Confirm API returns an error.
3. Confirm group status remains `READY_TO_CHECKOUT`.
4. Finalize as `u001` and confirm success.

### Bug 5: Duplicate Group Buy Link Ignores Creator User ID

Area: Backend

Feature affected:
Group-buy link/session generation and duplicate-session rules.

Bug behavior:
Group-buy IDs are generated only from `productId`, such as `/group-buy/p001`, instead of `productId + creatorUserId`, such as `/group-buy/p001-u001`.

Expected correct behavior:
Each creator should have a deterministic product-specific link: `/group-buy/{productId}-{creatorUserId}`. Multiple users should be able to start separate group buys for the same product.

Suggested reproduction steps:
1. As `u001`, start a group buy for `p001`.
2. As `u002`, start a group buy for `p001`.
3. Observe both users are sent to the same group-buy link, or the second user is blocked incorrectly.

Suggested validation after fix:
1. As `u001`, start `p001` group buy and confirm `/group-buy/p001-u001`.
2. As `u002`, start `p001` group buy and confirm `/group-buy/p001-u002`.
3. Confirm both sessions exist independently.

## More Complex Bug Set

### Bug 1: Existing Active Group Buy Redirects Without Creating Creator Order

Area: Backend / Frontend

Feature affected:
Duplicate start flow after an active creator session already exists.

Bug behavior:
If the creator clicks `Group Buy` again for the same product while they already have an active group buy, checkout still lets them place an order, but the backend returns the existing group-buy session without creating a new order. The frontend then redirects to the group-buy page as if checkout succeeded.

Expected correct behavior:
If an active group buy already exists for the same `productId + creatorUserId`, the user should be redirected to the existing group-buy page before or during checkout without pretending that a new order was placed.

Suggested reproduction steps:
1. As `u001`, start a group buy for `p001`.
2. Complete checkout and reach order confirmation.
3. Go back to the same product detail page.
4. Click `Group Buy` again.
5. Place order again from checkout.
6. Observe that the app redirects to the existing group-buy page without creating a new order confirmation or order.

Suggested validation after fix:
1. Repeat the sequence.
2. Confirm the second attempt clearly redirects to the existing group-buy page before creating a fake checkout completion.
3. Confirm order count does not increase.
4. Confirm the UI does not imply that a new order was placed.

### Bug 2: READY_TO_CHECKOUT Can Regress Back To PENDING After Serialization

Area: Backend

Feature affected:
Group-buy status transition and serialized API responses.

Bug behavior:
After enough unique users join and the group reaches `READY_TO_CHECKOUT`, a later API read or unrelated order serialization recalculates the group-buy status incorrectly and sets it back to `PENDING`.

Expected correct behavior:
Once participant count reaches `requiredGroupSize`, the group should remain `READY_TO_CHECKOUT` until the creator finalizes it into `SUCCESS` or it expires.

Suggested reproduction steps:
1. As `u001`, start a group buy for a product requiring 2 participants.
2. As `u002`, join the same group buy.
3. Confirm the group status becomes `READY_TO_CHECKOUT`.
4. Visit order confirmation pages for related orders or refresh the group-buy page multiple times.
5. Observe status incorrectly changes back to `PENDING`.

Suggested validation after fix:
1. Repeat the flow.
2. Confirm status becomes `READY_TO_CHECKOUT`.
3. Refresh group-buy and order confirmation pages.
4. Confirm status remains `READY_TO_CHECKOUT`.
5. Confirm creator can still finalize.

### Bug 3: Finalization Confirms Orders Across Multiple Group Buys For Same Product

Area: Backend

Feature affected:
Creator finalization and related order updates.

Bug behavior:
When one group buy is finalized, the backend confirms all pending group-buy orders for the same product, regardless of `groupBuyId`.

Expected correct behavior:
Finalization should only confirm orders where `order.groupBuyId === finalizedGroupBuy.id`.

Suggested reproduction steps:
1. As `u001`, start group buy for `p001`.
2. As `u002`, start a separate group buy for `p001`.
3. Add enough participants to make only `p001-u001` ready.
4. Finalize `p001-u001` as `u001`.
5. Open order details for `p001-u002`.
6. Observe unrelated orders are also `CONFIRMED`.

Suggested validation after fix:
1. Repeat the same setup.
2. Finalize only `p001-u001`.
3. Confirm only orders with `groupBuyId: p001-u001` are `CONFIRMED`.
4. Confirm `p001-u002` orders remain `PENDING_GROUP_BUY`.

### Bug 4: Join Checkout Uses URL Product ID Instead Of Group-Buy Product ID

Area: Frontend / Backend

Feature affected:
Join existing group-buy checkout.

Bug behavior:
When joining an existing group buy, the checkout page trusts the `productId` query parameter instead of deriving product details from the `groupBuyId`.

Expected correct behavior:
When `groupBuyId` exists, checkout should load the group-buy session first and use its `productId` as the source of truth. The URL product ID should either be ignored or validated before rendering checkout.

Suggested reproduction steps:
1. Start a group buy for `p001`.
2. Manually open `/checkout?productId=p002&purchaseType=GROUP_BUY&groupBuyId=p001-u001`.
3. Observe checkout renders product/pricing for `p002`.
4. Place order.
5. Observe backend error or inconsistent product mismatch behavior.

Suggested validation after fix:
1. Open the manipulated URL again.
2. Confirm checkout displays `p001`, the product attached to `p001-u001`.
3. Place order as a user who has not joined.
4. Confirm the order is created for `p001` and attached to `p001-u001`.

### Bug 5: Quantity Changes Price Totals But Backend Stores Per-Unit Discount Incorrectly

Area: Frontend / Backend

Feature affected:
Checkout quantity, price breakdown, and order confirmation consistency.

Bug behavior:
The checkout page correctly updates final payable for quantity changes, but the backend stores `discountAmount` as a per-unit discount instead of total discount across quantity.

Expected correct behavior:
Backend `discountAmount` should represent total discount for the order quantity, matching checkout and confirmation.

Suggested reproduction steps:
1. Start group-buy checkout for `p001`.
2. Set quantity to `3`.
3. Confirm checkout shows discount `-$30.00` and final payable `$59.97`.
4. Place order.
5. Open order confirmation or fetch `/api/orders/{orderId}`.
6. Observe `discountAmount` is `10.00` instead of `30.00`.

Suggested validation after fix:
1. Repeat quantity `3` group-buy checkout.
2. Confirm checkout discount is `-$30.00`.
3. Confirm order API returns `discountAmount: 30.00`.
4. Confirm final price remains `$59.97`.

## Single-Agent Complex Bug Set

### Bug 1: Duplicate Creator Checkout Creates an Extra Pending Order But Reuses Existing Group Buy

Area: Backend / Frontend

Feature affected:
Repeated group-buy start flow for the same creator and product.

Bug behavior:
If a creator already has an active group buy for a product, clicking `Group Buy` again and placing checkout creates another `PENDING_GROUP_BUY` order for the same user and same group-buy session, even though the participant list still only counts the creator once.

Expected correct behavior:
A creator with an active group buy for the same product should be redirected to the existing group-buy page and should not create another order.

Suggested reproduction steps:
1. As `u001`, start group buy for `p001` and place order.
2. Return to `p001` product detail.
3. Click `Group Buy` again and place order again.
4. Inspect order confirmation or `/api/orders/...`.
5. Observe a second pending group-buy order exists for the same creator/session.

Suggested validation after fix:
1. Repeat the same flow.
2. Confirm the second attempt redirects to existing group-buy page.
3. Confirm no additional order is created.
4. Confirm participant count remains `1`.

### Bug 2: READY_TO_CHECKOUT Status Is Correct In Group Page But Stale In Order Confirmation

Area: Backend / Frontend

Feature affected:
Status consistency between group-buy page and order confirmation page.

Bug behavior:
After enough users join and the group becomes `READY_TO_CHECKOUT`, the group-buy page shows `READY_TO_CHECKOUT`, but existing order confirmation pages still show `PENDING` because the embedded `order.groupBuy.status` is stale or not recalculated.

Expected correct behavior:
Order confirmation should show the current group-buy status from the associated session.

Suggested reproduction steps:
1. As `u001`, start a group buy for a product requiring 2 participants.
2. Open creator's order confirmation and note status is `PENDING`.
3. As `u002`, join the same group buy.
4. Open the group-buy page and confirm status is `READY_TO_CHECKOUT`.
5. Reopen creator's order confirmation.
6. Observe it still shows `PENDING`.

Suggested validation after fix:
1. Repeat the flow.
2. Confirm group-buy page shows `READY_TO_CHECKOUT`.
3. Confirm creator and joiner order confirmation pages also show `READY_TO_CHECKOUT`.

### Bug 3: Finalize Confirms Orders For Same Product Instead Of Same Group Buy

Area: Backend

Feature affected:
Creator finalization and order status updates.

Bug behavior:
When the creator finalizes one group buy, the backend confirms all pending group-buy orders for the same product, including orders from other group-buy sessions started by other creators.

Expected correct behavior:
Only orders whose `groupBuyId` matches the finalized group-buy session should be marked `CONFIRMED`.

Suggested reproduction steps:
1. As `u001`, start group buy for `p001`.
2. As `u002`, start a separate group buy for `p001`.
3. Add enough participants only to `p001-u001` so it becomes `READY_TO_CHECKOUT`.
4. Finalize `p001-u001` as `u001`.
5. Inspect order status for `p001-u002`.
6. Observe unrelated orders were marked `CONFIRMED`.

Suggested validation after fix:
1. Repeat the setup.
2. Finalize `p001-u001`.
3. Confirm only `p001-u001` orders become `CONFIRMED`.
4. Confirm `p001-u002` orders remain `PENDING_GROUP_BUY`.

### Bug 4: Join Checkout Renders Product From Query Param Instead Of Group Buy

Area: Frontend / Backend

Feature affected:
Joining an existing group-buy link through checkout.

Bug behavior:
When a user joins an existing group buy, checkout uses `productId` from the URL query string instead of the product attached to `groupBuyId`. A manipulated URL can show the wrong product and price before failing or submitting inconsistent data.

Expected correct behavior:
If `groupBuyId` exists, checkout should load the group-buy session and use `groupBuy.product.id` as the source of truth.

Suggested reproduction steps:
1. As `u001`, start group buy for `p001`.
2. Switch to `u002`.
3. Open `/checkout?productId=p002&purchaseType=GROUP_BUY&groupBuyId=p001-u001`.
4. Observe checkout displays `p002` product/pricing.
5. Place order.
6. Observe mismatch error or inconsistent checkout behavior.

Suggested validation after fix:
1. Open the same manipulated URL.
2. Confirm checkout displays `p001`, sourced from `p001-u001`.
3. Place order as `u002`.
4. Confirm order is created for `p001` and attached to `p001-u001`.

### Bug 5: Quantity-Based Discount Mismatch Between Checkout And Order API

Area: Backend / Frontend

Feature affected:
Group-buy quantity, price breakdown, and order confirmation.

Bug behavior:
Checkout correctly updates group-buy discount and final payable for quantity changes, but backend stores `discountAmount` as the single-unit discount instead of total discount for the selected quantity.

Expected correct behavior:
For quantity `N`, `discountAmount` should be `(normalPrice - groupBuyPrice) * N`, and `finalPrice` should be `groupBuyPrice * N`.

Suggested reproduction steps:
1. Start group-buy checkout for `p001`.
2. Set quantity to `3`.
3. Confirm checkout shows final payable `$59.97` and discount `-$30.00`.
4. Place order.
5. Inspect order confirmation or `/api/orders/{orderId}`.
6. Observe `discountAmount` is `$10.00` instead of `$30.00`.

Suggested validation after fix:
1. Repeat quantity `3`.
2. Confirm checkout discount is `-$30.00`.
3. Confirm order API returns `discountAmount: 30.00`.
4. Confirm final price remains `$59.97`.

## Simple Bug Examples

### Simple Bug 1: Checkout Final Total Ignores Quantity

Area: Frontend / Backend

Feature affected:
Checkout price summary.

Bug behavior:
When the user changes quantity, the checkout page still calculates final payable using a single unit.

Example:
- Product normal price: `$29.99`
- Group-buy price: `$19.99`
- Quantity: `3`

Incorrect checkout display:
- Original unit price: `$29.99`
- Discount: `-$10.00`
- Final payable: `$19.99`

Expected correct behavior:
- Original unit price: `$29.99`
- Discount: `-$30.00`
- Final payable: `$59.97`

### Simple Bug 2: Checkout Quantity Accepts Zero Or Negative Values

Area: Frontend / Backend

Feature affected:
Checkout quantity input and order creation.

Bug behavior:
The checkout quantity field allows `0`, `-1`, alphabetical input, or other invalid values, and the UI/backend uses that value to calculate totals or create orders.

Example:
- User enters quantity `-2`
- Checkout may show a negative payable amount or negative discount
- Backend may create an order with invalid quantity

Expected correct behavior:
Quantity should be validated so it is always a positive whole number.
