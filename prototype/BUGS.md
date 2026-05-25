# Planted Bugs

Each bug is small, isolated, and patchable by Codex with a 1-5 line fix.
They span three categories so the demo shows variety: **state bug**,
**validation bug**, **authorization bug**.

---

## Bug #1 — Stale `total_savings` in `GET /api/teams/{team_id}`

**Category:** State / business logic
**Location:** `main.py`, `get_team()` function
**Severity:** Medium — misleads users about discount

### What happens
The `total_savings` field is computed using a hardcoded `expected_member_count = 2`
instead of the actual current number of members. A team with 1 member still
shows savings as if 2 members had joined.

### How a persona finds it
1. Persona starts a team (1 member, themselves)
2. Persona looks at the team page → sees inflated "total savings so far"
3. Persona notes: "the savings number doesn't match the actual team size"

### Expected fix
```python
# Before
expected_member_count = 2
total_savings = product["price"] * TEAM_DISCOUNT * expected_member_count

# After
total_savings = product["price"] * TEAM_DISCOUNT * len(members)
```

### Regression test
`tests/test_planted_bugs.py::test_bug1_team_total_savings_should_reflect_actual_member_count`

---

## Bug #2 — Negative quantity accepted in `POST /api/teams/{team_id}/join`

**Category:** Input validation
**Location:** `main.py`, `join_team()` function
**Severity:** Critical — financial exposure (refunds on checkout)

### What happens
The join endpoint does not validate that `quantity > 0`. A malicious user can
submit `quantity = -1`, then check out, and the checkout endpoint multiplies
unit_price × -1 to produce a negative total = effective refund.

### How a persona finds it
Adversarial persona (the "scammer" archetype) probes by sending negative,
zero, and string quantities. Bug #2 surfaces immediately.

### Expected fix
```python
# Add near the top of join_team(), before the DB insert
if req.quantity <= 0:
    raise HTTPException(400, "Quantity must be positive")
```

### Regression test
`tests/test_planted_bugs.py::test_bug2_join_team_should_reject_negative_quantity`
`tests/test_planted_bugs.py::test_bug2_join_team_should_reject_zero_quantity`

---

## Bug #3 — Team creator can join their own team

**Category:** Authorization / state
**Location:** `main.py`, `join_team()` function
**Severity:** High — abuses the "team complete = discount" rule

### What happens
The join endpoint does not check whether the joining user is the same as the
team creator. The creator is auto-joined as member #1 when the team is
created, then can call `/join` again to become member #2, triggering the
"team complete" condition without a real second buyer.

### How a persona finds it
Adversarial persona attempts to claim the team discount solo by joining
their own team. Also catchable by a "confused user" persona who clicks
"join" on their own team page.

### Expected fix
```python
# Add after the team lookup, before the insert
if req.user_id == team["creator_id"]:
    raise HTTPException(400, "Cannot join your own team")
```

### Regression test
`tests/test_planted_bugs.py::test_bug3_creator_cannot_join_own_team`

---

## Why these three?

| Bug | Category | Codex skill demonstrated |
|---|---|---|
| #1 | State / business logic | Reading, understanding, refactoring existing logic |
| #2 | Input validation | Defensive programming, edge case handling |
| #3 | Authorization | Cross-table reasoning, state-aware checks |

Each can be:
- **Found** by a persona behaving normally or adversarially (not contrived)
- **Diagnosed** from the logs + a quick read of the file
- **Fixed** with a small, surgical patch (1-5 lines)
- **Validated** by a regression test Codex can write

The demo can showcase any 1-2 of these depending on time. Bug #2 is the
most dramatic (negative-money refund = audible reaction). Bug #3 is the
sneakiest (looks fine in casual testing). Bug #1 is the easiest visual
("this number is wrong").
