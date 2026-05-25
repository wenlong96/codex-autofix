# Prototype — TeamBuy SG

Shopee-style team-purchase service. The thing personas will test and the
self-healing orchestrator will patch.

## Run it

```bash
cd prototype

# 1. install deps
pip install -r requirements.txt

# 2. seed the DB with sample products
python seed.py

# 3. start the server
python main.py
# (or: uvicorn main:app --reload)
```

Open http://localhost:8000

## What's in here

- `main.py` — FastAPI backend, all routes
- `seed.py` — drops + recreates `prototype.db` with 6 sample products
- `static/index.html` + `static/app.js` — frontend (vanilla JS SPA)
- `tests/test_planted_bugs.py` — pytest demonstrating each bug
- `BUGS.md` — the 3 planted bugs documented with fixes

## Demo flow (manual sanity check)

1. Open http://localhost:8000 → see 6 products.
2. Click any product → product detail page.
3. Click "Start a team" → redirected to team page with share URL.
4. Open the share URL in a different browser / incognito (different `user_id`) → click "Join this team".
5. Back on the first browser, refresh → team is complete, can checkout at 15% off.

## Verifying the bugs exist

```bash
cd prototype
python -m pytest tests/ -v
```

You should see the `test_bug1_*`, `test_bug2_*`, `test_bug3_*` tests **FAIL**.
That's correct — the bugs are present. After self-healing, they should pass.

The "happy path" tests should pass already.

## Triggering bugs manually (for persona scripting)

```bash
# Bug 1 — stale total_savings
curl -X POST http://localhost:8000/api/teams \
  -H "Content-Type: application/json" \
  -d '{"product_id": 1, "user_id": "alice"}'
# Then GET the team; look at total_savings — should be inflated.

# Bug 2 — negative quantity
curl -X POST http://localhost:8000/api/teams/<team_id>/join \
  -H "Content-Type: application/json" \
  -d '{"user_id": "bob", "quantity": -1}'
# Returns 200 (should be 400)

# Bug 3 — self-join
curl -X POST http://localhost:8000/api/teams/<team_id>/join \
  -H "Content-Type: application/json" \
  -d '{"user_id": "alice", "quantity": 1}'
# Returns 200 (alice is the creator, should be 400)
```

## Logs

The middleware writes every request to a `logs` table. The orchestrator
reads from:
- `GET /api/_logs/recent` — last N requests
- `GET /api/_logs/errors` — last N requests with status >= 400

## Next steps

Phase 1 (this) → working prototype with planted bugs ✅
Phase 2 → one Playwright-driven persona that navigates the site
Phase 3 → self-healing orchestrator that patches a known bug
Phase 4 → dashboard
Phase 5 → integration + scale to 20 + 80 personas
