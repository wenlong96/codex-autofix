# Agent Implementation Plan — Hackathon Build

Status: **planning / selection locked.** This is the working spec for the 5
agents we committed to building (down from the 9 in `AGENT_ROSTER.txt`). Written
to be followed with **no other reference open** — every file path, function
name, line target, planted bug, and regression test is spelled out here.

Last updated: 2026-06-03.

---

## 0. Context you need before touching anything

The existing pipeline (do **not** change its shape — every new agent plugs into
it unchanged):

```
reset → discovery (agents explore) → aggregate_bugs() → verify_all()
      → Codex heal (per verified bug) → re-validate → scoreboard
```

Key facts, verified against the current code (not the docs — the docs lie in
two places, noted below):

- **Discovery roster is hardcoded** at `orchestrator/full_loop.py:94`:
  `DISCOVERY_PERSONAS = ["kelvin", "priya", "hassan"]`. Adding an agent to a run
  = adding its id here (until we build the registry, see §4).
- **Every agent must emit a `PersonaReport`** (`personas/run_one.py:55`). The
  only field the downstream pipeline reads for bugs is `possible_bugs:
  list[str]` (plus `persona_id` / `persona_name` for attribution). See
  `aggregate_bugs()` at `orchestrator/full_loop.py:184` — it just flattens
  `.possible_bugs` from each report into `[(persona_id, bug_text), ...]`.
- **The verifier reads the actual source** to classify each bug string as
  real / misunderstanding / duplicate (`orchestrator/verifier.py`). So a planted
  bug must be *genuinely present in the code* the verifier can read, or it gets
  rejected as a phantom. Frontend bugs live in `prototype/static/` — confirm the
  verifier's `source_root` reaches those files (it is passed
  `source_root=prototype/` in `verify_all`).
- **Codex heals against a regression test.** Every planted bug needs a failing
  test that asserts *correct* behaviour, so the heal loop has a target to turn
  green. Tests go in `prototype/tests/test_regressions.py`.

### ⚠️ Doc discrepancies to not get burned by

1. `prototype/BUGS.md` references tests named `tests/test_planted_bugs.py::...`.
   **That file does not exist.** The real test file is
   `prototype/tests/test_regressions.py` and the test names are different
   (e.g. `test_join_team_rejects_negative_quantity`, not
   `test_bug2_join_team_should_reject_negative_quantity`). Add new tests to
   `test_regressions.py`.
2. The promo-code `<input>` **already has a `<label>`** (`static/app.js:109`
   for solo, `:194` for team). The accessibility bug below is therefore planted
   by *removing / breaking* that label association — it is not missing today.

### Baseline state (so you know what "done" looks like)

`cd prototype && python -m pytest tests/ -q` today → **6 failures, 3 passes**.
The 6 failures are planted bugs #1–#5 (negative + zero quantity are two tests
for the same bug #2). After we plant 3 more frontend bugs, expect **9 failures**
until Codex heals them.

After editing `prototype/main.py`, refresh the frozen baseline so Stage 0 resets
to the right thing: `copy prototype\main.py prototype\main.py.buggy`. (Frontend
bugs in `static/` are not part of the `main.py.buggy` snapshot — Stage 0 only
restores `main.py`. If a frontend heal mutates `static/`, restore it manually
between demo runs, e.g. from git.)

---

## 1. Selected agents (the 5 we are building)

| # | Agent | Tier | Type | Bug it catches | Bug status |
|---|-------|------|------|----------------|------------|
| FE-1 | Mobile / small-screen user | 1 | Frontend persona | Card/button overflow < 400px viewport | **plant new** |
| FE-2 | Accessibility user | 1 | Frontend persona | Promo input label association broken | **plant new** (break existing label) |
| FE-3 | Confused / low-tech user | 1 | Frontend persona | Double-click "Buy" → two orders | **plant new** |
| BE-1 | API Fuzzer / Contract agent | 2 | Backend inspector | Negative/zero quantity accepted (bug #2) | **already exists + tested** |
| BE-2 | Security / Auth agent | 2 | Backend inspector | Creator joins own team (bug #3) | **already exists + tested** |

Why this set: BE-1 and BE-2 catch bugs that **already exist** and are invisible
to the current vision personas (`BUGS.md` marks #2/#3 "API-only — latent"). Zero
backend planting; just build the agents and two latent bugs start getting caught
→ verified → healed live. The 3 frontend agents each catch a class the others
physically can't (responsive / a11y / double-submit), so deselecting any one
visibly drops a find — that is the "holistic team" proof.

Deliberately **excluded**: the Adversary persona (Tier 1) — it targets backend
bugs via a flaky vision loop; BE-1/BE-2 do that job deterministically instead.

---

## 2. Frontend agents (Tier 1) — reuse the existing browser/vision loop

These are just new `Persona` entries. They run through the *exact* same
`run_persona` / `run_persona_async` loop as kelvin/priya/hassan. No new
mechanism except: FE-1 needs a narrow viewport, FE-2 needs DOM/ARIA reading.

### Shared steps for every frontend agent

1. Add a `Persona` to `personas/persona_profiles.py` and register it in
   `ALL_PERSONAS` (the dict at line ~216).
2. Add its id to `DISCOVERY_PERSONAS` in `orchestrator/full_loop.py:94`.
3. Plant the bug (see each agent below).
4. Add a failing regression test to `prototype/tests/test_regressions.py`.
5. Route the persona to `llm_provider="openai", llm_model="gpt-4o-mini"` (the
   existing three all do this — Gemini Flash-Lite drops multi-step goals).

### FE-1 — Mobile / small-screen user

- **Persona:** archetype `mobile`. Goal text: "Shop on a narrow phone screen.
  Open a product, read the price card and the Buy buttons. If any text, price,
  or button is cut off, runs off the side of the screen, or you have to scroll
  sideways to read it, that is a bug — report it and describe what overflowed."
- **New mechanism needed:** the loop must launch the browser at a phone
  viewport (~360–390px wide). Find where Playwright creates the page/context in
  `personas/run_one.py` (search for `viewport` / `new_context` / `new_page`)
  and thread a `viewport_width` param from the `Persona` (add an optional field
  like `viewport: tuple[int,int] | None = None`) down to context creation.
  Default `None` = current desktop behaviour, so the other personas are
  unaffected.
- **Bug to plant** (`prototype/static/app.js`, `viewProductDetail`, the buttons
  block ~line 101–117): make the Buy buttons overflow on narrow screens. Replace
  the responsive `w-full` on `#btn-solo` (or the promo block) with a fixed wide
  width, e.g. `class="w-[480px] ..."`, so on a 360px viewport the button runs
  off the right edge. Keep it a 1-line change so Codex's fix is surgical
  (revert to `w-full`).
- **Regression test:** `test_buy_button_fits_mobile_viewport`. A pure-DOM/CSS
  assertion is awkward in the FastAPI TestClient (no layout engine). Two
  options, pick one:
  - (a) Assert the offending class string is absent from the served HTML/JS
    (`GET /static/app.js` should not contain `w-[480px]`). Cheap, deterministic,
    test-client-friendly. **Recommended for hackathon.**
  - (b) A Playwright test that loads the page at 360px and asserts
    `scrollWidth <= clientWidth`. More faithful, more setup.

### FE-2 — Accessibility user

- **Persona:** archetype `a11y`. Goal text: "You navigate by screen reader and
  keyboard only — you cannot see the page. For every form input, check it has a
  programmatic label (a `<label for=...>` that matches the input `id`, or an
  `aria-label`). If an input has no associated accessible name, report it: a
  screen-reader user cannot tell what to type."
- **New mechanism needed:** this agent should read the **DOM/ARIA tree**, not
  the screenshot. Cheapest implementation: in `run_one.py`, when the persona's
  archetype is `a11y`, additionally pass the page's accessibility-relevant HTML
  (e.g. `page.content()` or `page.accessibility.snapshot()`) into the prompt
  alongside (or instead of) the screenshot. Gate this on archetype so other
  personas are unchanged.
- **Bug to plant** (`prototype/static/app.js`): break the label association on
  the promo input. Today (`:109`) the label is a sibling `<label>` with no
  `for`, and the input is `#promo-solo`. Make it genuinely inaccessible: remove
  the `<label>` element entirely (or give the input no `id`/`aria-label`). The
  correct fix Codex restores: `<label for="promo-solo">…</label>` +
  `id="promo-solo"`, or add `aria-label="Promo code"` to the input.
- **Regression test:** `test_promo_input_has_accessible_label`. Serve the JS
  (`GET /static/app.js`) and assert it contains either `for="promo-solo"` paired
  with an `id="promo-solo"`, or `aria-label=` on the promo input. (String/regex
  assertion against the served static file — same pattern as FE-1 option (a).)

### FE-3 — Confused / low-tech user

- **Persona:** archetype `low_tech`. Goal text: "You are not very comfortable
  with computers. When a button doesn't seem to respond instantly you click it
  again, and you sometimes hit Back and retry. Buy a product. If your clicking
  results in being charged twice / two order confirmations / two orders, report
  it."
- **New mechanism needed:** the action schema already supports `click`. To
  reliably reproduce a double-submit, add a small affordance: allow the persona
  to emit two consecutive `click` actions on the same button, OR add an optional
  `double: true` flag on the click action handled in `run_one.py` that fires the
  click twice in quick succession. Keep it opt-in.
- **Bug to plant:** the double-submit is *latent today* — `#btn-solo` /
  `#btn-checkout` in `app.js` are not disabled after the first click, and
  `POST /api/checkout` (`main.py:283`) has no idempotency guard, so two rapid
  clicks create two `orders` rows. To make it **healable + testable**, plant the
  fix target on the **backend** (cleaner to test than frontend timing):
  - Decide the correct behaviour: a repeated checkout with the same
    (user_id, product_id, team_id) within a short window, or carrying an
    idempotency key, should not create a second order.
  - Simplest demoable version: add an optional `idempotency_key` to
    `CheckoutRequest` and have the confused-user agent send the same key twice;
    correct behaviour returns the same `order_id` both times. The buggy baseline
    ignores the key and inserts twice.
- **Regression test:** `test_duplicate_checkout_is_idempotent`. POST
  `/api/checkout` twice with identical body (+ idempotency key); assert only one
  `orders` row exists for that key / the same `order_id` is returned both times.
- **Note:** FE-3 is the highest-effort frontend agent (needs a backend change +
  the double-click affordance). If time is tight on the day, **cut FE-3 first**
  and demo with FE-1 + FE-2 + the two backend agents.

---

## 3. Backend agents (Tier 2) — new mechanism, same report schema

These do **not** drive a browser and do **not** use a vision model. They hit the
API directly with `requests`/`httpx`, decide if behaviour is wrong, and emit a
`PersonaReport` with `possible_bugs` populated so the rest of the pipeline is
unchanged. Both are **deterministic** — no LLM, no flakiness. This is their
whole value on demo day.

### Shared steps for both backend agents

1. Create `orchestrator/inspectors.py` (new file). Each inspector is a function
   `run_<name>_inspector(target_url: str) -> PersonaReport` that:
   - imports `PersonaReport` from `personas.run_one`,
   - makes its probe requests against `target_url`,
   - appends a clear, specific string to `possible_bugs` for each violation
     (include the endpoint, the input, the observed vs expected status — the
     verifier reads source to confirm, so be precise),
   - returns a filled `PersonaReport` (set `persona_id` e.g. `"api_fuzzer"`,
     `persona_name` e.g. `"API Fuzzer"`, `completed_purchase=False`,
     `final_assessment` summarising what it probed).
2. Wire them into `orchestrator/full_loop.py`: after the persona discovery
   reports are collected into the `reports` dict (around the discovery stage,
   ~line 290+), call each inspector and insert its report:
   `reports["api_fuzzer"] = run_api_fuzzer_inspector(target_url)`. Because they
   return the same dataclass, `aggregate_bugs()` / `verify_all()` pick them up
   with no other change.
3. Gate them behind a flag (e.g. `--no-inspectors`) so we can show "personas
   only" vs "personas + inspectors" in the demo (the selection-matters moment).
4. **No bug-planting and no new tests** — bugs #2 and #3 and their tests already
   exist in `test_regressions.py`.

### BE-1 — API Fuzzer / Contract agent → catches bug #2

- **Probe:** create a team (`POST /api/teams` with `{"product_id":1,
  "user_id":"fuzz"}`), grab `team_id`, then `POST /api/teams/{team_id}/join`
  with boundary quantities: `-1`, `0`, a huge value, a non-int string.
- **Oracle (what's wrong):** `quantity <= 0` should be rejected with `400`. The
  buggy baseline (`main.py:254` `join_team`) has no validation and returns `200`.
  When status is `200` for `quantity <= 0`, append a bug like: "POST
  /api/teams/{id}/join accepted quantity=-1 with HTTP 200; expected 400. A
  negative quantity flows into checkout and produces a negative (refund) total."
- **Healed-state target:** test `test_join_team_rejects_negative_quantity` and
  `test_join_team_rejects_zero_quantity` go green (Codex adds
  `if req.quantity <= 0: raise HTTPException(400, ...)`).

### BE-2 — Security / Auth agent → catches bug #3 (+ room for IDOR)

- **Probe:** `POST /api/teams` as user `alice` → `team_id`. Then `POST
  /api/teams/{team_id}/join` as the **same** user `alice`.
- **Oracle:** a creator joining their own team should be rejected with `400`
  (you can't form a real 2-person team with one human). Buggy baseline returns
  `200` and flips the team to "complete", unlocking the discount solo. When the
  self-join returns `200`, append: "POST /api/teams/{id}/join allowed the team
  creator (alice) to join their own team (HTTP 200), reaching member_count=2 and
  unlocking the team discount without a second real buyer. Expected 400."
- **Healed-state target:** test `test_creator_cannot_join_own_team` goes green
  (Codex adds `if req.user_id == team["creator_id"]: raise HTTPException(400,
  ...)`).
- **Stretch (only if ahead of schedule):** add an IDOR probe — `GET
  /api/teams/{id}` for a team the caller didn't create and flag if it leaks
  another user's order/member data. This needs a new planted bug + test; skip
  unless time allows.

---

## 4. Cross-cutting: selectable agent registry (do this if time allows)

The roster's headline feature. Today the roster is the hardcoded list at
`full_loop.py:94`. Generalise it so the user picks agents per run:

- Define a registry mapping `id -> {kind: "persona"|"inspector", factory}`.
  Personas resolve via `get_persona(id)`; inspectors resolve to their
  `run_*_inspector` function.
- Add a CLI flag `--agents kelvin,priya,api_fuzzer,...` (default = all 8 once
  built, or a curated demo set). The discovery stage iterates the selected
  persona ids; the inspector stage iterates the selected inspector ids.
- This is what makes "enable/disable an agent and watch a find appear/disappear"
  a one-flag demo instead of a code edit. **Lower priority than getting the 5
  agents working** — manual edits to `DISCOVERY_PERSONAS` + the `--no-inspectors`
  flag cover the demo if we run out of time.

---

## 5. Build order (5-hour budget, highest payoff first)

1. **BE-1 + BE-2** (~45 min). Biggest payoff: bugs + tests already exist, fully
   deterministic, two latent bugs start getting caught → healed live. Build
   `inspectors.py`, wire into `full_loop`, add `--no-inspectors`.
2. **FE-2 Accessibility** (~45 min). Deterministic-ish (DOM read), 1-line bug,
   string-assertion test.
3. **FE-1 Mobile** (~45 min). High visual drama (button off-screen), viewport
   plumbing + 1-line CSS bug + string-assertion test.
4. **Registry + `--agents` flag** (~30 min) if ahead.
5. **FE-3 Confused user** (~60 min). Cut this first if behind — needs a backend
   idempotency change + double-click affordance.
6. **Record a clean run for the dashboard** (see §6). Do this with ~45 min to
   spare, not at the buzzer.

---

## 6. Should we still use the existing personas (kelvin / priya / hassan)?

**Yes — keep them. Do not drop them.** Reasoning:

- They are the project's entire differentiator. The pitch is "personas explore a
  live site through a vision model like real users and the loop auto-fixes what
  they find." Cut them and you're left with deterministic API checkers — useful,
  but that's a linter, not the story.
- They already work end-to-end and cover three real UI-discoverable bugs (#1
  stale savings, #4 promo-not-applied, #5 price mismatch) that the new agents do
  **not** target. Removing them shrinks the demo's bug coverage.

**But manage their demo risk** — they are the flakiest part (vision model, rate
limits, parallel-browser timing, multi-step goal-following):

- Run **one** persona headed/live as the spotlight (priya is the default and the
  most visually interesting — fills a promo field, completes checkout). Let the
  **dashboard replay** (it's replay-first by design, README §"The dashboard")
  carry the full multi-agent run so a live rate-limit can't sink the demo.
- Make the **deterministic Tier 2 inspectors the live backbone** — they always
  work, so even if a persona stalls on stage, the inspectors still find + heal
  the backend bugs in real time.
- Do **not** run all 8 agents live in parallel — that maximises the chance of a
  429. Keep all 8 in the *recorded* run the dashboard replays; run a small
  subset live.
- Use `--sequential` / a larger `--stagger` for any live persona run to avoid
  per-minute token limits.

**One-line answer for the team:** keep the personas (they're the differentiator
and cover bugs nothing else does), but on the day lean on the recorded
dashboard replay + the deterministic inspectors for anything that has to work
live; run only the spotlight persona truly live.

---

## 7. Definition of done (verification checklist)

- [ ] `cd prototype && python -m pytest tests/ -q` shows the expected failure
      count: 6 (baseline) + 1 per planted frontend bug we added.
- [ ] BE-1 and BE-2 each produce a `possible_bugs` entry against the buggy
      baseline, and **no** entry once `main.py` is healed (so re-validation is
      clean).
- [ ] Each new persona appears in a discovery run and flags its target bug.
- [ ] `verify_all` classifies each new bug as **real** (not phantom) — confirm
      the verifier can read the file the bug lives in (`static/` for FE bugs).
- [ ] Codex heals each verified bug and the matching regression test goes green.
- [ ] `copy prototype\main.py prototype\main.py.buggy` run after backend edits,
      so Stage 0 resets correctly. Frontend `static/` bugs restored from git
      between runs.
- [ ] A clean full run recorded to `personas/reports/` for the dashboard.
