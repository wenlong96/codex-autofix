"""
Generate product-vision agent reports for the proposed group-buy prototype.

The current runnable app is still the team-purchase prototype. This module is
for the product-vision branch: it reads the group-buy proposal/test-suite docs
and emits agent-shaped reports that show which future agents should catch which
documented group-buy bugs.

Usage:
    python -B -m orchestrator.group_buy_vision_reports
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "personas"))

from personas.run_one import PersonaReport  # noqa: E402


BUG_PROPOSALS = PROJECT_ROOT / "prototype" / "BUG_PROPOSALS.md"
TEST_SUITE = PROJECT_ROOT / "prototype" / "TEST_CASE_SUITE.md"
REPORT_DIR = PROJECT_ROOT / "personas" / "reports"


def _read_context() -> dict[str, str]:
    missing = [p for p in (BUG_PROPOSALS, TEST_SUITE) if not p.exists()]
    if missing:
        names = ", ".join(str(p) for p in missing)
        raise FileNotFoundError(f"Missing required group-buy doc(s): {names}")
    return {
        "bug_proposals": BUG_PROPOSALS.read_text(encoding="utf-8"),
        "test_suite": TEST_SUITE.read_text(encoding="utf-8"),
    }


def _report(
    persona_id: str,
    persona_name: str,
    assessment: str,
    bugs: list[str],
) -> PersonaReport:
    now = time.time()
    return PersonaReport(
        persona_id=persona_id,
        persona_name=persona_name,
        target_url="docs://prototype/group-buy",
        started_at=now,
        finished_at=now,
        completed_purchase=False,
        final_assessment=assessment,
        friction_points=[],
        possible_bugs=bugs,
        observations=[],
    )


def generate_group_buy_reports() -> dict[str, PersonaReport]:
    # Reading the docs is a deliberate precondition. The mapping below is kept
    # deterministic so a demo run is stable and easy to compare over time.
    _read_context()

    reports = {
        "gb_flow_persona": _report(
            "gb_flow_persona",
            "Group-Buy Flow Persona",
            (
                "Targets user-visible checkout and session lifecycle issues: "
                "starting, re-starting, joining, and preserving share links."
            ),
            [
                "TC-004 / Proposal Initial Bug 1: Group Buy button creates or opens a group-buy session before checkout; expected checkout URL with purchaseType=GROUP_BUY&startGroupBuy=true first.",
                "TC-009 / Single-Agent Bug 1: duplicate creator checkout creates an extra pending order instead of redirecting to the existing active group-buy session.",
                "TC-010 / Initial Bug 5: group-buy links are generated from productId only, so multiple creators cannot start independent sessions for the same product.",
                "TC-011: joining an existing group buy should count the joiner only after checkout succeeds, not when the join page opens.",
            ],
        ),
        "gb_price_persona": _report(
            "gb_price_persona",
            "Price-Sensitive Checkout Persona",
            (
                "Targets visible pricing trust bugs: original unit price, "
                "discount amount, quantity totals, and confirmation consistency."
            ),
            [
                "TC-006 / Initial Bug 2: group-buy checkout displays the discounted group-buy price as the original unit price; expected original unit price, discount, and final payable.",
                "TC-007 / Single-Agent Bug 5: quantity=3 shows the right checkout total but backend/order API stores discountAmount as a one-unit discount instead of total discount.",
                "Simple Bug 1: checkout final total ignores quantity and still shows a single-unit final payable.",
                "TC-021: order confirmation should preserve the same product, original unit price, discount, final paid price, and group-buy link shown during checkout.",
            ],
        ),
        "gb_contract_fuzzer": _report(
            "gb_contract_fuzzer",
            "Group-Buy API Contract Fuzzer",
            (
                "Targets backend contract boundaries and manipulated request "
                "state that ordinary shoppers usually cannot produce."
            ),
            [
                "TC-008 / Simple Bug 2: checkout quantity accepts zero, negative, decimal, alphabetic, or blank values; expected INVALID_QUANTITY and no order.",
                "TC-013 / Single-Agent Bug 4: join checkout trusts URL productId instead of deriving product details from groupBuyId; manipulated URL can render or submit the wrong product.",
                "TC-022: invalid product, group-buy, and order routes should return clear not-found errors instead of inconsistent or leaking responses.",
            ],
        ),
        "gb_security_auth": _report(
            "gb_security_auth",
            "Group-Buy Security / Auth Agent",
            (
                "Targets permission and isolation bugs around finalization and "
                "cross-session state updates."
            ),
            [
                "TC-017 / Initial Bug 4: non-creator can finalize a ready group buy; expected ONLY_CREATOR_CAN_FINALIZE and unchanged READY_TO_CHECKOUT status.",
                "TC-018: creator cannot finalize before required size is reached; expected GROUP_BUY_SIZE_NOT_REACHED.",
                "TC-019 / Single-Agent Bug 3: finalizing one group buy confirms orders for the same product across other group-buy sessions; expected only matching groupBuyId orders to change.",
            ],
        ),
        "gb_data_integrity": _report(
            "gb_data_integrity",
            "Group-Buy Data Integrity Agent",
            (
                "Targets invariant drift across participant counts, statuses, "
                "order snapshots, and repeated reads."
            ),
            [
                "TC-007 / Initial Bug 3: participant count uses quantity instead of unique users; quantity=3 from one user should still count as one participant.",
                "TC-015 / Single-Agent Bug 2: group-buy page shows READY_TO_CHECKOUT while order confirmation pages still show stale PENDING status.",
                "More Complex Bug 2: READY_TO_CHECKOUT can regress back to PENDING after serialization or unrelated order reads.",
                "TC-024: group-buy page should refresh participant count and status after each join without stale display.",
            ],
        ),
    }
    return reports


def recommended_subset() -> list[str]:
    return [
        "gb_price_persona",
        "gb_contract_fuzzer",
        "gb_security_auth",
        "gb_data_integrity",
    ]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate group-buy product-vision agent reports from docs."
    )
    parser.add_argument(
        "--include-flow",
        action="store_true",
        help="include the flow persona in the recommended subset summary",
    )
    args = parser.parse_args()

    started = time.time()
    reports = generate_group_buy_reports()
    subset = recommended_subset()
    if args.include_flow:
        subset = ["gb_flow_persona", *subset]

    raw_bugs = [
        {"persona_id": pid, "bug": bug}
        for pid, rpt in reports.items()
        for bug in rpt.possible_bugs
    ]

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = REPORT_DIR / f"group_buy_vision_reports_{int(started)}.json"
    payload = {
        "started_at": started,
        "ended_at": time.time(),
        "source_docs": [str(BUG_PROPOSALS), str(TEST_SUITE)],
        "recommended_subset": subset,
        "report_count": len(reports),
        "raw_bug_count": len(raw_bugs),
        "reports": {pid: asdict(rpt) for pid, rpt in reports.items()},
        "raw_bugs": raw_bugs,
    }
    out_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("Group-buy product-vision agent reports")
    print(f"  Reports: {len(reports)}")
    print(f"  Raw bug catches: {len(raw_bugs)}")
    print(f"  Recommended subset: {', '.join(subset)}")
    for pid in subset:
        rpt = reports[pid]
        print(f"  - {rpt.persona_name} ({pid}): {len(rpt.possible_bugs)} catch(es)")
    print(f"  Saved: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
