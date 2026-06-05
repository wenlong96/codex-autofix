# Prototype - GroupBuy Lab

Runnable group-buy prototype for the product-vision branch. It intentionally
plants group-buy bugs that match the branch's product-vision agents.

## Run It

```bash
cd prototype
pip install -r requirements.txt
python seed.py
python main.py
```

Open http://localhost:8000/products

## What's In Here

- `main.py` - FastAPI backend for products, checkout, group buys, orders, and finalization.
- `main.py.buggy` - reset baseline with the product-vision planted bugs.
- `seed.py` - drops and recreates `prototype.db` with four group-buy products.
- `static/index.html` and `static/app.js` - vanilla JS frontend.
- `tests/test_regressions.py` - tests for the correct behavior; planted bug tests fail by design.
- `BUGS.md` - private answer key for the branch-specific planted bugs.
- `BUG_PROPOSALS.md` and `TEST_CASE_SUITE.md` - broader group-buy QA planning docs.

## Expected Test Result

```bash
cd prototype
python -m pytest tests -q
```

Expected before healing:

```text
6 failed, 2 passed
```

The passing tests cover product loading and normal checkout. The failing tests
cover the planted group-buy bugs for the flow, pricing, contract, security, and
data-integrity agents.
