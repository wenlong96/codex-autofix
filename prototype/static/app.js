// Group-buy prototype SPA.
// Pages: /products, /products/:id, /checkout, /group-buy/:id, /orders/:id

const $app = document.getElementById("app");
const $user = document.getElementById("user-badge");

const USERS = ["u001", "u002", "u003", "u004"];

function getUserId() {
  let uid = sessionStorage.getItem("mock_user_id");
  if (!uid) {
    uid = "u001";
    sessionStorage.setItem("mock_user_id", uid);
  }
  return uid;
}

function setUserId(uid) {
  sessionStorage.setItem("mock_user_id", uid);
  render();
}

function fmt(amount) {
  return "$" + Number(amount).toFixed(2);
}

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`API ${res.status}: ${text}`);
  }
  return res.json();
}

function navigate(path) {
  window.history.pushState({}, "", path);
  render();
}

function query() {
  return new URLSearchParams(window.location.search);
}

document.addEventListener("click", (e) => {
  const link = e.target.closest("a[data-nav]");
  if (link) {
    e.preventDefault();
    navigate(link.getAttribute("href"));
  }
});
window.addEventListener("popstate", render);

function renderUserSwitcher() {
  $user.innerHTML = USERS.map((uid) => {
    const active = uid === getUserId();
    return `<button data-user="${uid}" class="px-2 py-1 rounded ${active ? "bg-white text-orange-600" : "bg-orange-600 text-white"}">${uid}</button>`;
  }).join("");
  $user.querySelectorAll("button[data-user]").forEach((btn) => {
    btn.onclick = () => setUserId(btn.dataset.user);
  });
}

async function viewProducts() {
  const products = await api("/api/products");
  $app.innerHTML = `
    <div class="mb-6">
      <h1 class="text-2xl font-bold">Group-buy deals</h1>
      <p class="text-sm text-gray-600">Start a group, invite friends, and unlock the lower price.</p>
    </div>
    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
      ${products.map((p) => `
        <a href="/products/${p.id}" data-nav class="bg-white border border-gray-200 rounded-lg p-4 hover:shadow-sm">
          <img src="${p.image_url}" alt="${p.name}" class="w-full aspect-[4/3] object-cover rounded" />
          <div class="mt-3 text-xs text-gray-500">${p.id}</div>
          <div class="font-semibold">${p.name}</div>
          <div class="mt-2 flex items-baseline gap-2">
            <span class="text-gray-500 line-through">${fmt(p.normal_price)}</span>
            <span class="text-orange-600 text-xl font-bold">${fmt(p.group_buy_price)}</span>
          </div>
          <div class="text-xs text-gray-600">Needs ${p.required_group_size} participants</div>
        </a>
      `).join("")}
    </div>
  `;
}

async function viewProduct(productId) {
  const p = await api(`/api/products/${productId}`);
  $app.innerHTML = `
    <a href="/products" data-nav class="text-sm text-gray-500 hover:underline">Back to products</a>
    <section class="bg-white border border-gray-200 rounded-lg mt-4 p-5 grid md:grid-cols-[260px_1fr] gap-6">
      <img src="${p.image_url}" alt="${p.name}" class="w-full aspect-[4/3] object-cover rounded" />
      <div>
        <div class="text-xs text-gray-500">${p.id}</div>
        <h1 class="text-2xl font-bold">${p.name}</h1>
        <p class="text-gray-600 mt-2">${p.description}</p>
        <div class="mt-5 grid grid-cols-2 gap-3">
          <div class="bg-gray-50 rounded p-3">
            <div class="text-xs text-gray-500">Normal price</div>
            <div class="text-xl font-bold">${fmt(p.normal_price)}</div>
          </div>
          <div class="bg-orange-50 border border-orange-200 rounded p-3">
            <div class="text-xs text-orange-700">Group-buy price</div>
            <div class="text-xl font-bold text-orange-600">${fmt(p.group_buy_price)}</div>
          </div>
        </div>
        <div class="mt-5 space-y-2">
          <button id="btn-buy" class="w-full bg-gray-900 text-white rounded py-2 font-medium">Buy Now</button>
          <button id="btn-group" class="w-full bg-orange-500 text-white rounded py-2 font-medium">Group Buy</button>
        </div>
      </div>
    </section>
  `;

  document.getElementById("btn-buy").onclick = () => {
    navigate(`/checkout?productId=${p.id}&purchaseType=NORMAL`);
  };

  document.getElementById("btn-group").onclick = async () => {
    // PLANTED FLOW BUG: creates a group-buy session before checkout instead of
    // navigating to checkout with startGroupBuy=true.
    const group = await api("/api/group-buys", {
      method: "POST",
      body: JSON.stringify({ product_id: p.id, user_id: getUserId() }),
    });
    navigate(`/group-buy/${group.id}`);
  };
}

async function viewCheckout() {
  const params = query();
  const productId = params.get("productId");
  const purchaseType = params.get("purchaseType") || "NORMAL";
  const groupBuyId = params.get("groupBuyId");
  const startGroupBuy = params.get("startGroupBuy") === "true";
  if (!productId) {
    $app.innerHTML = `<div class="text-red-600">Missing productId</div>`;
    return;
  }

  // PLANTED CONTRACT BUG: if groupBuyId is present, this still trusts productId
  // from the URL instead of loading the group-buy's product.
  const p = await api(`/api/products/${productId}`);
  const isGroup = purchaseType === "GROUP_BUY";

  $app.innerHTML = `
    <section class="bg-white border border-gray-200 rounded-lg p-5">
      <div class="text-xs text-gray-500">Checkout as ${getUserId()}</div>
      <h1 class="text-2xl font-bold mt-1">${p.name}</h1>
      <p class="text-sm text-gray-600">${isGroup ? "Group-buy checkout" : "Normal checkout"}</p>

      <label class="block mt-5 text-sm font-medium">Quantity</label>
      <input id="qty" value="1" class="mt-1 border border-gray-300 rounded px-3 py-2 w-28" />

      <div class="mt-5 bg-gray-50 rounded p-4 text-sm space-y-2">
        <div class="flex justify-between">
          <span>Original unit price</span>
          <span id="unit-price"></span>
        </div>
        <div class="flex justify-between">
          <span>Discount</span>
          <span id="discount"></span>
        </div>
        <div class="flex justify-between font-bold text-lg pt-2 border-t">
          <span>Final payable</span>
          <span id="final"></span>
        </div>
      </div>

      <button id="place-order" class="mt-5 w-full bg-orange-500 text-white rounded py-2 font-medium">Place Order</button>
    </section>
  `;

  function refreshSummary() {
    const qty = Number(document.getElementById("qty").value || 1);
    if (isGroup) {
      // PLANTED PRICING BUGS: displays the discounted price as the unit price,
      // and final payable ignores quantity.
      document.getElementById("unit-price").textContent = fmt(p.group_buy_price);
      document.getElementById("discount").textContent = "-" + fmt(p.normal_price - p.group_buy_price);
      document.getElementById("final").textContent = fmt(p.group_buy_price);
    } else {
      document.getElementById("unit-price").textContent = fmt(p.normal_price);
      document.getElementById("discount").textContent = fmt(0);
      document.getElementById("final").textContent = fmt(p.normal_price * qty);
    }
  }

  document.getElementById("qty").oninput = refreshSummary;
  refreshSummary();

  document.getElementById("place-order").onclick = async () => {
    const quantity = Number(document.getElementById("qty").value);
    const order = await api("/api/orders", {
      method: "POST",
      body: JSON.stringify({
        user_id: getUserId(),
        product_id: p.id,
        purchase_type: purchaseType,
        quantity,
        group_buy_id: groupBuyId || null,
        start_group_buy: startGroupBuy,
      }),
    });
    navigate(`/orders/${order.id}`);
  };
}

async function viewGroupBuy(groupBuyId) {
  const g = await api(`/api/group-buys/${groupBuyId}`);
  $app.innerHTML = `
    <section class="bg-white border border-gray-200 rounded-lg p-5">
      <div class="text-xs text-gray-500">Group buy ${g.id}</div>
      <h1 class="text-2xl font-bold mt-1">${g.product.name}</h1>
      <div class="mt-4 grid grid-cols-2 gap-3">
        <div class="bg-gray-50 rounded p-3">
          <div class="text-xs text-gray-500">Status</div>
          <div class="font-bold">${g.status}</div>
        </div>
        <div class="bg-gray-50 rounded p-3">
          <div class="text-xs text-gray-500">Participants</div>
          <div class="font-bold">${g.participant_count}/${g.required_group_size}</div>
        </div>
      </div>
      <div class="mt-4 text-sm text-gray-600">Creator: ${g.creator_user_id}</div>
      <div class="mt-4 bg-gray-100 rounded p-2 font-mono text-sm break-all">${window.location.origin}/group-buy/${g.id}</div>

      <div class="mt-5 space-y-2">
        <button id="join" class="w-full bg-orange-500 text-white rounded py-2 font-medium">Join Group Buy</button>
        <button id="finalize" class="w-full bg-green-600 text-white rounded py-2 font-medium">Finalize Group Buy</button>
      </div>
    </section>
  `;

  document.getElementById("join").onclick = () => {
    navigate(`/checkout?productId=${g.product_id}&purchaseType=GROUP_BUY&groupBuyId=${g.id}`);
  };
  document.getElementById("finalize").onclick = async () => {
    await api(`/api/group-buys/${g.id}/finalize`, {
      method: "POST",
      body: JSON.stringify({ user_id: getUserId() }),
    });
    render();
  };
}

async function viewOrder(orderId) {
  const order = await api(`/api/orders/${orderId}`);
  $app.innerHTML = `
    <section class="bg-white border border-gray-200 rounded-lg p-5 text-center">
      <div class="text-4xl">OK</div>
      <h1 class="text-2xl font-bold mt-2">Order placed</h1>
      <div class="text-sm text-gray-600">Order ${order.id}</div>
      <div class="mt-5 text-left bg-gray-50 rounded p-4 space-y-2 text-sm">
        <div class="flex justify-between"><span>Product</span><span>${order.product.name}</span></div>
        <div class="flex justify-between"><span>Status</span><span>${order.status}</span></div>
        <div class="flex justify-between"><span>Quantity</span><span>${order.quantity}</span></div>
        <div class="flex justify-between"><span>Discount stored</span><span>${fmt(order.discount_amount)}</span></div>
        <div class="flex justify-between font-bold text-lg pt-2 border-t"><span>Final paid</span><span>${fmt(order.final_price)}</span></div>
      </div>
      ${order.group_buy_id ? `<a href="/group-buy/${order.group_buy_id}" data-nav class="inline-block mt-5 bg-orange-500 text-white px-4 py-2 rounded">View group buy</a>` : ""}
    </section>
  `;
}

async function render() {
  renderUserSwitcher();
  const path = window.location.pathname;
  try {
    if (path === "/" || path === "/products") return viewProducts();
    const productMatch = path.match(/^\/products\/([\w-]+)$/);
    if (productMatch) return viewProduct(productMatch[1]);
    if (path === "/checkout") return viewCheckout();
    const groupMatch = path.match(/^\/group-buy\/([\w-]+)$/);
    if (groupMatch) return viewGroupBuy(groupMatch[1]);
    const orderMatch = path.match(/^\/orders\/([\w-]+)$/);
    if (orderMatch) return viewOrder(orderMatch[1]);
    $app.innerHTML = `<div class="text-red-600">Not found</div>`;
  } catch (e) {
    $app.innerHTML = `<div class="text-red-600">Error: ${e.message}</div>`;
  }
}

render();
