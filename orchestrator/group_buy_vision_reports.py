"""
Generate LLM-autonomous product-vision agent reports for the proposed group-buy
prototype.

The current runnable app is still the team-purchase prototype. This module is
for the product-vision branch: each group-buy agent reads the proposal/test
suite docs, reasons from its own mission, and emits an agent-shaped report.

Usage:
    python -B -m orchestrator.group_buy_vision_reports
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "personas"))

from personas.llm_client import get_llm_client  # noqa: E402
from personas.run_one import Observation, PersonaReport  # noqa: E402


BUG_PROPOSALS = PROJECT_ROOT / "prototype" / "BUG_PROPOSALS.md"
TEST_SUITE = PROJECT_ROOT / "prototype" / "TEST_CASE_SUITE.md"
REPORT_DIR = PROJECT_ROOT / "personas" / "reports"


AGENT_SPECS: dict[str, dict[str, str]] = {
    "gb_flow_persona": {
        "name": "Group-Buy Flow Persona",
        "mission": (
            "Act like a user focused on the start, restart, join, checkout, "
            "and share-link lifecycle. Find bugs that interrupt or misrepresent "
            "the intended group-buy journey."
        ),
    },
    "gb_price_persona": {
        "name": "Price-Sensitive Checkout Persona",
        "mission": (
            "Act like a price-sensitive shopper who audits checkout math, unit "
            "prices, discounts, quantities, payable totals, and confirmation "
            "screens."
        ),
    },
    "gb_contract_fuzzer": {
        "name": "Group-Buy API Contract Fuzzer",
        "mission": (
            "Act like an autonomous API contract tester. Find invalid inputs, "
            "tampered query parameters, boundary quantities, and source-of-truth "
            "mismatches that a normal UI flow may hide."
        ),
    },
    "gb_security_auth": {
        "name": "Group-Buy Security / Auth Agent",
        "mission": (
            "Act like a security and authorization reviewer. Find permission, "
            "ownership, finalization, and cross-session isolation bugs."
        ),
    },
    "gb_data_integrity": {
        "name": "Group-Buy Data Integrity Agent",
        "mission": (
            "Act like a data-integrity reviewer. Find invariant drift across "
            "participants, order status, group-buy status, serialization, and "
            "refresh/read flows."
        ),
    },
}


def _read_context() -> dict[str, str]:
    missing = [p for p in (BUG_PROPOSALS, TEST_SUITE) if not p.exists()]
    if missing:
        names = ", ".join(str(p) for p in missing)
        raise FileNotFoundError(f"Missing required group-buy doc(s): {names}")
    return {
        "bug_proposals": BUG_PROPOSALS.read_text(encoding="utf-8"),
        "test_suite": TEST_SUITE.read_text(encoding="utf-8"),
    }


def _docs_prompt(context: dict[str, str]) -> str:
    return (
        "BUG_PROPOSALS.md:\n"
        f"{context['bug_proposals']}\n\n"
        "TEST_CASE_SUITE.md:\n"
        f"{context['test_suite']}"
    )


def _report(
    persona_id: str,
    persona_name: str,
    assessment: str,
    bugs: list[str],
    observations: list[Observation] | None = None,
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
        observations=observations or [],
    )


def _effective_llm_label(
    llm_provider: str | None = None,
    llm_model: str | None = None,
) -> tuple[str, str]:
    provider = (llm_provider or os.environ.get("LLM_PROVIDER", "gemini")).lower()
    if llm_model:
        return provider, llm_model
    if provider == "openai":
        return provider, os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    if provider == "gemini":
        return provider, os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite")
    return provider, "(env default)"


def _short_finding(finding: str, limit: int = 96) -> str:
    compact = " ".join(finding.split())
    return compact if len(compact) <= limit else compact[: limit - 3] + "..."


def _doc_review_observations(
    mission: str,
    bugs: list[str],
) -> list[Observation]:
    observations = [
        Observation(
            step=1,
            page_url="docs://prototype/group-buy",
            persona_thought=(
                "Read BUG_PROPOSALS.md and TEST_CASE_SUITE.md through this "
                "agent's mission lens."
            ),
            action_taken={
                "type": "doc_review",
                "source_docs": [
                    str(BUG_PROPOSALS.relative_to(PROJECT_ROOT)),
                    str(TEST_SUITE.relative_to(PROJECT_ROOT)),
                ],
                "focus": mission,
            },
            friction_noted=None,
        )
    ]
    for step, bug in enumerate(bugs, 2):
        observations.append(
            Observation(
                step=step,
                page_url="docs://prototype/group-buy",
                persona_thought=f"Selected a finding aligned with this mission: {_short_finding(bug)}",
                action_taken={
                    "type": "doc_review",
                    "finding": bug,
                },
                friction_noted=None,
            )
        )
    return observations


def _agent_system_prompt(persona_name: str, mission: str) -> str:
    return f"""You are {persona_name}, an autonomous QA agent for a proposed group-buy ecommerce prototype.

Mission:
{mission}

You are reading product/design QA documents, not running code yet. Your job is
to decide which documented bugs this agent would be especially good at catching
once the group-buy prototype is implemented.

Return ONLY JSON:
{{
  "final_assessment": "2-3 sentences describing your strategy and coverage",
  "possible_bugs": [
    "specific bug this agent would catch, with test case/proposal reference and expected behavior"
  ]
}}

Rules:
- Prefer the highest-signal 3-5 findings for this agent.
- Use concrete references such as TC-013 or Proposal Initial Bug 4 when present.
- Do not report bugs outside this agent's mission.
- Do not invent implementation details not present in the docs."""


def _run_llm_doc_agent(
    persona_id: str,
    context: dict[str, str],
    llm_provider: str | None = None,
    llm_model: str | None = None,
    verbose: bool = True,
) -> PersonaReport:
    spec = AGENT_SPECS[persona_id]
    if verbose:
        provider, model = _effective_llm_label(llm_provider, llm_model)
        print(
            f"[{persona_id}] starting (doc_review_agent) "
            f"planner=llm provider={provider} model={model}"
        )
        print(f"[{persona_id}] step 1 | read: BUG_PROPOSALS.md + TEST_CASE_SUITE.md")
    llm = get_llm_client(provider=llm_provider, model=llm_model)
    result = llm.complete_json(
        system=_agent_system_prompt(spec["name"], spec["mission"]),
        user=_docs_prompt(context),
        temperature=0.35,
        max_tokens=1800,
    )
    possible_bugs = result.get("possible_bugs", [])
    if not isinstance(possible_bugs, list):
        possible_bugs = []
    bugs = [str(b) for b in possible_bugs if str(b).strip()]
    observations = _doc_review_observations(spec["mission"], bugs)
    if verbose:
        for step, bug in enumerate(bugs, 2):
            print(f"[{persona_id}] step {step} | report: {_short_finding(bug)}")
        print(f"[{persona_id}] done - {len(observations)} steps, {len(bugs)} bugs flagged")
    return _report(
        persona_id=persona_id,
        persona_name=spec["name"],
        assessment=str(result.get("final_assessment", "")).strip(),
        bugs=bugs,
        observations=observations,
    )


def generate_group_buy_reports(
    planner: str = "llm",
    llm_provider: str | None = None,
    llm_model: str | None = None,
    verbose: bool = True,
) -> dict[str, PersonaReport]:
    context = _read_context()
    if planner == "llm":
        return {
            persona_id: _run_llm_doc_agent(
                persona_id,
                context,
                llm_provider=llm_provider,
                llm_model=llm_model,
                verbose=verbose,
            )
            for persona_id in AGENT_SPECS
        }
    return _generate_deterministic_group_buy_reports(verbose=verbose)


def _deterministic_agent_report(
    persona_id: str,
    assessment: str,
    bugs: list[str],
    verbose: bool = True,
) -> PersonaReport:
    spec = AGENT_SPECS[persona_id]
    observations = _doc_review_observations(spec["mission"], bugs)
    if verbose:
        print(f"[{persona_id}] starting (doc_review_agent) planner=deterministic")
        print(f"[{persona_id}] step 1 | read: BUG_PROPOSALS.md + TEST_CASE_SUITE.md")
        for step, bug in enumerate(bugs, 2):
            print(f"[{persona_id}] step {step} | report: {_short_finding(bug)}")
        print(f"[{persona_id}] done - {len(observations)} steps, {len(bugs)} bugs flagged")
    return _report(
        persona_id,
        spec["name"],
        assessment,
        bugs,
        observations=observations,
    )


def _generate_deterministic_group_buy_reports(
    verbose: bool = True,
) -> dict[str, PersonaReport]:
    _read_context()
    return {
        "gb_flow_persona": _deterministic_agent_report(
            "gb_flow_persona",
            "Deterministic fallback mapping for flow/session lifecycle issues.",
            [
                "TC-004: Group Buy button creates or opens a session before checkout.",
                "TC-009: duplicate creator checkout creates an extra pending order.",
                "TC-010: product-only group-buy links collapse multiple creators into one session.",
            ],
            verbose=verbose,
        ),
        "gb_price_persona": _deterministic_agent_report(
            "gb_price_persona",
            "Deterministic fallback mapping for checkout pricing bugs.",
            [
                "TC-006: group-buy checkout shows discounted price as original unit price.",
                "TC-007: quantity=3 stores one-unit discount instead of total discount.",
                "Simple Bug 1: checkout final total ignores quantity.",
            ],
            verbose=verbose,
        ),
        "gb_contract_fuzzer": _deterministic_agent_report(
            "gb_contract_fuzzer",
            "Deterministic fallback mapping for contract and tampering bugs.",
            [
                "TC-008: invalid checkout quantity is accepted.",
                "TC-013: join checkout trusts URL productId instead of groupBuyId.",
                "TC-022: invalid routes should return clear not-found errors.",
            ],
            verbose=verbose,
        ),
        "gb_security_auth": _deterministic_agent_report(
            "gb_security_auth",
            "Deterministic fallback mapping for authorization bugs.",
            [
                "TC-017: non-creator can finalize group buy.",
                "TC-018: creator can finalize before required size is reached.",
                "TC-019: finalization confirms orders outside the finalized groupBuyId.",
            ],
            verbose=verbose,
        ),
        "gb_data_integrity": _deterministic_agent_report(
            "gb_data_integrity",
            "Deterministic fallback mapping for status and invariant bugs.",
            [
                "TC-007: participant count uses quantity instead of unique users.",
                "TC-015: order confirmations show stale PENDING after READY_TO_CHECKOUT.",
                "More Complex Bug 2: READY_TO_CHECKOUT regresses back to PENDING.",
            ],
            verbose=verbose,
        ),
    }


def default_recommended_subset() -> list[str]:
    return [
        "gb_price_persona",
        "gb_contract_fuzzer",
        "gb_security_auth",
        "gb_data_integrity",
    ]


def _coordinator_system_prompt() -> str:
    return """You are an autonomous QA-team coordinator.

Given several agent reports for a proposed group-buy prototype, choose the best
subset for a demo. Optimize for clear coverage, believable autonomy, bug variety,
and low overlap.

Return ONLY JSON:
{
  "recommended_subset": ["agent_id", "agent_id"],
  "reasoning": "1-3 sentences"
}

Choose 3-5 agents. Use only ids present in the reports."""


def recommended_subset(
    reports: dict[str, PersonaReport],
    planner: str = "llm",
    include_flow: bool = False,
    llm_provider: str | None = None,
    llm_model: str | None = None,
) -> tuple[list[str], str]:
    if planner != "llm":
        subset = default_recommended_subset()
        if include_flow:
            subset = ["gb_flow_persona", *subset]
        return subset, "Deterministic fallback subset."

    llm = get_llm_client(provider=llm_provider, model=llm_model)
    report_summary: dict[str, Any] = {
        pid: {
            "name": rpt.persona_name,
            "assessment": rpt.final_assessment,
            "possible_bugs": rpt.possible_bugs,
        }
        for pid, rpt in reports.items()
    }
    result = llm.complete_json(
        system=_coordinator_system_prompt(),
        user=json.dumps(report_summary, indent=2),
        temperature=0.25,
        max_tokens=1000,
    )
    subset = result.get("recommended_subset", [])
    if not isinstance(subset, list):
        subset = []
    clean_subset = [str(pid) for pid in subset if str(pid) in reports]
    if include_flow and "gb_flow_persona" not in clean_subset:
        clean_subset = ["gb_flow_persona", *clean_subset]
    if not clean_subset:
        clean_subset = default_recommended_subset()
    return clean_subset, str(result.get("reasoning", "")).strip()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate group-buy product-vision agent reports from docs."
    )
    parser.add_argument(
        "--include-flow",
        action="store_true",
        help="include the flow persona in the recommended subset summary",
    )
    parser.add_argument(
        "--planner",
        choices=["llm", "deterministic"],
        default="llm",
        help="agent reasoning mode (default: llm)",
    )
    args = parser.parse_args()

    started = time.time()
    reports = generate_group_buy_reports(planner=args.planner)
    subset, subset_reasoning = recommended_subset(
        reports,
        planner=args.planner,
        include_flow=args.include_flow,
    )

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
        "target": "docs://prototype/group-buy",
        "source_docs": [str(BUG_PROPOSALS), str(TEST_SUITE)],
        "recommended_subset": subset,
        "recommended_subset_reasoning": subset_reasoning,
        "planner": args.planner,
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
    if subset_reasoning:
        print(f"  Why: {subset_reasoning}")
    for pid in subset:
        rpt = reports[pid]
        print(f"  - {rpt.persona_name} ({pid}): {len(rpt.possible_bugs)} catch(es)")
    print(f"  Saved: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
