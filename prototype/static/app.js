// TeamBuy SG - vanilla JS SPA-ish routing
// Pages: /, /product/:id, /team/:id, /order/:id

const $app = document.getElementById("app");
const $badge = document.getElementById("user-badge");

// Per-tab user id - personas can run in separate browser contexts and have
// distinct user_ids.
function getUserId() {
  let uid = sessionStorage.getItem("user_id");
  if (!uid) {
    uid = "u_" + Math.random().toString(36).slice(2, 10);
    sessionStorage.setItem("user_id", uid);
  }
  return uid;
}

function fmt(amount) {
  return "S$" + Number(amount).toFixed(2);
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

// Intercept anchor clicks for SPA navigation
document.addEventListener("click", (e) => {
  const link = e.target.closest("a[data-nav]");
  if (link) {
    e.preventDefault();
    navigate(link.getAttribute("href"));
  }
});
window.addEventListener("popstate", render);

// ---------------------------------------------------------------------------
// Views
// ---------------------------------------------------------------------------

async function viewProductList() {
  const products = await api("/api/products");
  $app.innerHTML = `
    <h1 class="text-2xl font-bold mb-1">Today's Picks</h1>
    <p class="text-sm text-gray-600 mb-6">Team up with 1 other person, both get 15% off.</p>
    <div class="grid grid-cols-2 md:grid-cols-3 gap-4">
      ${products
        .map(
          (p) => `
        <a href="/product/${p.id}" data-nav class="bg-white rounded-lg shadow-sm hover:shadow-md transition p-3 block">
          <img src="${p.image_url}" alt="${p.name}" class="w-full aspect-square object-cover rounded" />
          <div class="mt-2 font-medium text-sm">${p.name}</div>
          <div class="flex items-baseline gap-2">
            <div class="text-orange-600 font-bold">${fmt(p.display_price ?? p.price)}</div>
            ${p.display_price && p.display_price < p.price
              ? `<div class="text-xs text-gray-400 line-through">${fmt(p.price)}</div>`
              : ""}
          </div>
          <div class="text-xs text-green-700 mt-1">Team price: ${fmt(p.price * 0.85)}</div>
        </a>
      `,
        )
        .join("")}
    </div>
  `;
}

async function viewProductDetail(productId) {
  const p = await api(`/api/products/${productId}`);
  $app.innerHTML = `
    <a href="/" data-nav class="text-sm text-gray-500 hover:underline">&larr; Back</a>
    <div class="bg-white rounded-lg shadow-sm mt-4 p-6 md:flex gap-8">
      <img src="${p.image_url}" alt="${p.name}" class="w-full md:w-64 aspect-square object-cover rounded" />
      <div class="mt-4 md:mt-0 flex-1">
        <h1 class="text-2xl font-bold">${p.name}</h1>
        <p class="text-gray-600 mt-2">${p.description}</p>

        <div class="mt-6">
          <div class="text-sm text-gray-500">Solo price</div>
          <div class="text-2xl font-bold">${fmt(p.price)}</div>
        </div>

        <div class="mt-3 bg-orange-50 border border-orange-200 rounded p-3">
          <div class="text-sm text-orange-700 font-medium">Team purchase 15% off</div>
          <div class="text-2xl font-bold text-orange-600">${fmt(p.price * 0.85)}</div>
          <div class="text-xs text-gray-600">Get 1 friend to join your team, both pay this price.</div>
        </div>

        <div class="mt-6 space-y-2">
          <button id="btn-team" class="w-full bg-orange-500 hover:bg-orange-600 text-white py-2 rounded font-medium">
            Start a team
          </button>
          <button id="btn-solo" class="w-full bg-gray-200 hover:bg-gray-300 text-gray-800 py-2 rounded font-medium">
            Buy solo (${fmt(p.price)})
          </button>
          <div class="mt-3 pt-3 border-t">
            <label class="text-xs text-gray-500 block mb-1">Have a promo code? (e.g. SAVE10 for 10% off)</label>
            <input
              id="promo-solo"
              type="text"
              placeholder="Enter promo code"
              class="w-full border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring focus:ring-orange-200"
            />
          </div>
        </div>
      </div>
    </div>
  `;

  document.getElementById("btn-team").onclick = async () => {
    const data = await api("/api/teams", {
      method: "POST",
      body: JSON.stringify({ product_id: p.id, user_id: getUserId() }),
    });
    navigate(`/team/${data.team_id}`);
  };

  document.getElementById("btn-solo").onclick = async () => {
    const promo = (document.getElementById("promo-solo")?.value || "").trim();
    const data = await api("/api/checkout", {
      method: "POST",
      body: JSON.stringify({
        user_id: getUserId(),
        product_id: p.id,
        quantity: 1,
        promo_code: promo || null,
      }),
    });
    sessionStorage.setItem("last_order", JSON.stringify(data));
    navigate(`/order/${data.order_id}`);
  };
}

async function viewTeam(teamId) {
  const t = await api(`/api/teams/${teamId}`);
  const isCreator = t.team.creator_id === getUserId();
  const alreadyJoined = t.members.some((m) => m.user_id === getUserId());

  $app.innerHTML = `
    <a href="/" data-nav class="text-sm text-gray-500 hover:underline">&larr; Back</a>
    <div class="bg-white rounded-lg shadow-sm mt-4 p-6">
      <div class="text-xs text-gray-500">Team #${t.team.id}</div>
      <h1 class="text-2xl font-bold mt-1">${t.product.name}</h1>
      <p class="text-sm text-gray-600">${t.product.description}</p>

      <div class="mt-6 grid grid-cols-2 gap-4">
        <div class="bg-gray-50 rounded p-3">
          <div class="text-xs text-gray-500">Solo price</div>
          <div class="text-xl font-bold line-through text-gray-400">${fmt(t.product.price)}</div>
        </div>
        <div class="bg-orange-50 border border-orange-200 rounded p-3">
          <div class="text-xs text-orange-700">Team price (each)</div>
          <div class="text-xl font-bold text-orange-600">${fmt(t.product.price * 0.85)}</div>
        </div>
      </div>

      <div class="mt-4 text-sm">
        <span class="font-medium">${t.member_count}/2</span> members joined
        ${t.complete ? '<span class="ml-2 text-green-700 font-medium">[OK] Team complete</span>' : ""}
      </div>

      <div class="mt-2 text-sm text-green-800">
        Total savings so far: <span class="font-bold">${fmt(t.total_savings)}</span>
      </div>

      <div class="mt-6">
        <div class="text-xs text-gray-500">Share this link with a friend:</div>
        <div class="bg-gray-100 rounded p-2 text-sm font-mono break-all mt-1">
          ${window.location.origin}/team/${t.team.id}
        </div>
      </div>

      <div class="mt-6">
        ${
          alreadyJoined
            ? `<div class="text-sm text-gray-600 mb-2">You're in this team.</div>`
            : `<button id="btn-join" class="w-full bg-orange-500 hover:bg-orange-600 text-white py-2 rounded font-medium">Join this team</button>`
        }
        ${
          t.complete
            ? `<div class="mt-3 pt-3 border-t">
                <label class="text-xs text-gray-500 block mb-1">Have a promo code? (e.g. SAVE10 for 10% off)</label>
                <input
                  id="promo-team"
                  type="text"
                  placeholder="Enter promo code"
                  class="w-full border border-gray-300 rounded px-3 py-2 text-sm mb-2 focus:outline-none focus:ring focus:ring-orange-200"
                />
                <button id="btn-checkout" class="w-full bg-green-600 hover:bg-green-700 text-white py-2 rounded font-medium">Checkout at team price</button>
              </div>`
            : `<button class="w-full mt-2 bg-gray-200 text-gray-400 py-2 rounded font-medium cursor-not-allowed" disabled>Waiting for 1 more...</button>`
        }
      </div>
    </div>
  `;

  const btnJoin = document.getElementById("btn-join");
  if (btnJoin) {
    btnJoin.onclick = async () => {
      const qtyEl = document.querySelector("input[name=qty]");
      const quantity = qtyEl ? Number(qtyEl.value) : 1;
      try {
        await api(`/api/teams/${teamId}/join`, {
          method: "POST",
          body: JSON.stringify({ user_id: getUserId(), quantity }),
        });
        render();
      } catch (e) {
        alert("Couldn't join: " + e.message);
      }
    };
  }

  const btnCheckout = document.getElementById("btn-checkout");
  if (btnCheckout) {
    btnCheckout.onclick = async () => {
      const promo = (document.getElementById("promo-team")?.value || "").trim();
      const data = await api("/api/checkout", {
        method: "POST",
        body: JSON.stringify({
          user_id: getUserId(),
          team_id: teamId,
          product_id: t.product.id,
          quantity: 1,
          promo_code: promo || null,
        }),
      });
      sessionStorage.setItem("last_order", JSON.stringify(data));
      navigate(`/order/${data.order_id}`);
    };
  }
}

async function viewOrder(orderId) {
  // Pulls the most recent checkout response so we can show total, promo status etc.
  let order = null;
  try {
    order = JSON.parse(sessionStorage.getItem("last_order") || "null");
  } catch (e) {
    order = null;
  }

  const promoBanner = order && order.promo_applied
    ? `<div class="mt-3 inline-block bg-green-50 border border-green-300 text-green-800 rounded px-3 py-1 text-sm font-medium">
         [OK] Promo "${order.promo_code}" applied
       </div>`
    : "";

  const totalLine = order && typeof order.total === "number"
    ? `<div class="mt-3 text-sm text-gray-700">Total paid: <span class="font-bold">${fmt(order.total)}</span></div>`
    : "";

  $app.innerHTML = `
    <div class="bg-white rounded-lg shadow-sm mt-4 p-6 text-center">
      <div class="text-4xl">[OK]</div>
      <h1 class="text-2xl font-bold mt-2">Order placed</h1>
      <div class="text-sm text-gray-600 mt-1">Order #${orderId}</div>
      ${totalLine}
      ${promoBanner}
      <a href="/" data-nav class="inline-block mt-6 bg-orange-500 hover:bg-orange-600 text-white px-4 py-2 rounded font-medium">
        Keep shopping
      </a>
    </div>
  `;
}

// ---------------------------------------------------------------------------
// Router
// ---------------------------------------------------------------------------

function render() {
  const path = window.location.pathname;
  $badge.textContent = getUserId();

  try {
    if (path === "/") return viewProductList();
    const productMatch = path.match(/^\/product\/(\d+)$/);
    if (productMatch) return viewProductDetail(productMatch[1]);
    const teamMatch = path.match(/^\/team\/([\w-]+)$/);
    if (teamMatch) return viewTeam(teamMatch[1]);
    const orderMatch = path.match(/^\/order\/([\w-]+)$/);
    if (orderMatch) return viewOrder(orderMatch[1]);
    $app.innerHTML = "<div>Not found</div>";
  } catch (e) {
    $app.innerHTML = `<div class="text-red-600">Error: ${e.message}</div>`;
  }
}

render();
