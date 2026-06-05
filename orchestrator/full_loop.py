"""
full_loop.py — End-to-end demo with 3 specialist personas + verified heals.

Usage (from project root):
    python -m orchestrator.full_loop
    python -m orchestrator.full_loop --sequential          # don't run personas in parallel
    python -m orchestrator.full_loop --all-headless        # no browser windows at all
    python -m orchestrator.full_loop --skip-reset          # don't reset to baseline first
    python -m orchestrator.full_loop --no-revalidate       # skip the final re-validation pass

Demo arc:
    0. Reset prototype/main.py to all-bugs baseline.
    1. Discovery — three personas explore in parallel (Maria headed, Anh + Karim headless).
    2. Aggregate their bug reports. Verifier filters phantom / duplicate reports.
    3. For each verified bug, run the Codex heal loop. Promote on success.
    4. Re-validate with Maria (single headed run) against the patched site.
    5. Print summary + save transcript JSON.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "personas"))

load_dotenv()

from orchestrator.agent import heal, HealResult, DEFAULT_MODEL  # noqa: E402
from orchestrator.heal import make_streamer  # noqa: E402
from orchestrator.inspectors import run_backend_inspectors  # noqa: E402
from orchestrator.verifier import verify_bug, Verdict  # noqa: E402
from personas.persona_profiles import get_persona, Persona  # noqa: E402
from personas.run_one import (  # noqa: E402
    run_persona,
    run_persona_async,
    PersonaReport,
)


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------

LIVE_MAIN = PROJECT_ROOT / "prototype" / "main.py"
BUGGY_BASELINE = PROJECT_ROOT / "prototype" / "main.py.buggy"


def reset_prototype_to_baseline() -> bool:
    if not BUGGY_BASELINE.exists():
        print(f"  ⚠️  No baseline found at {BUGGY_BASELINE}. Skipping reset.")
        return False
    shutil.copy2(BUGGY_BASELINE, LIVE_MAIN)
    return True


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

BAR = "=" * 76
SUB = "-" * 76


def banner(title: str, char: str = "=") -> None:
    print()
    print(char * 76)
    print(f"  {title}")
    print(char * 76)


def _trim(obj: Any, n: int = 360) -> str:
    """Serialise and truncate a value for compact storage in transcripts."""
    if obj is None:
        return ""
    s = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, default=str)
    return s if len(s) <= n else s[: n - 3] + "..."


# ---------------------------------------------------------------------------
# Discovery — 3 personas in parallel
# ---------------------------------------------------------------------------

DISCOVERY_PERSONAS = ["kelvin", "priya", "hassan"]


async def run_discovery_parallel(
    target_url: str,
    max_steps: int,
    spotlight_persona_id: str = "maria",
    all_headless: bool = False,
    stagger_seconds: float = 6.0,
) -> dict[str, PersonaReport]:
    """
    Run all DISCOVERY_PERSONAS in parallel. One persona runs headed (the
    spotlight); the rest run headless.

    `stagger_seconds` introduces a small offset between persona starts so
    they don't all hit the same per-minute token bucket at the same instant.
    With 3 personas and ~6s stagger, the first one runs unimpeded, the second
    starts 6s later, the third 12s later — usually enough to spread token
    usage across the token-per-minute window.
    """
    async def _delayed(delay: float, coro):
        if delay > 0:
            await asyncio.sleep(delay)
        return await coro

    tasks = []
    for i, pid in enumerate(DISCOVERY_PERSONAS):
        persona = get_persona(pid)
        headless = all_headless or (pid != spotlight_persona_id)
        # Spotlight persona always goes first (zero delay) so the visible
        # browser opens immediately for the audience.
        delay = 0.0 if pid == spotlight_persona_id else stagger_seconds * (i + 1)
        coro = run_persona_async(
            persona=persona,
            target_url=target_url,
            max_steps=max_steps,
            headless=headless,
            verbose=True,
        )
        tasks.append(_delayed(delay, coro))

    reports = await asyncio.gather(*tasks, return_exceptions=True)
    out: dict[str, PersonaReport] = {}
    for pid, r in zip(DISCOVERY_PERSONAS, reports):
        if isinstance(r, Exception):
            print(f"  ⚠️  Persona {pid} failed: {type(r).__name__}: {r}")
            continue
        out[pid] = r
    return out


def run_discovery_sequential(
    target_url: str,
    max_steps: int,
    spotlight_persona_id: str = "maria",
    all_headless: bool = False,
) -> dict[str, PersonaReport]:
    out: dict[str, PersonaReport] = {}
    for pid in DISCOVERY_PERSONAS:
        persona = get_persona(pid)
        headless = all_headless or (pid != spotlight_persona_id)
        try:
            out[pid] = run_persona(
                persona=persona,
                target_url=target_url,
                max_steps=max_steps,
                headless=headless,
                verbose=True,
            )
        except Exception as e:
            print(f"  ⚠️  Persona {pid} failed: {type(e).__name__}: {e}")
    return out


def print_discovery_summary(reports: dict[str, PersonaReport]) -> None:
    print()
    print(SUB)
    print(f"  Discovery summary — {len(reports)} personas")
    print(SUB)
    for pid, rpt in reports.items():
        bugs = len(rpt.possible_bugs)
        print(f"  • {rpt.persona_name} ({pid}): {len(rpt.observations)} steps, {bugs} bug(s) flagged")
        for b in rpt.possible_bugs:
            print(f"      - {b[:180]}{'...' if len(b) > 180 else ''}")


# ---------------------------------------------------------------------------
# Aggregation + verification
# ---------------------------------------------------------------------------

def aggregate_bugs(reports: dict[str, PersonaReport]) -> list[tuple[str, str]]:
    """
    Flatten all possible_bugs into [(persona_id, bug_text), ...].
    Preserves report order so the demo narrative is deterministic.
    """
    out: list[tuple[str, str]] = []
    for pid, rpt in reports.items():
        for b in rpt.possible_bugs:
            out.append((pid, b))
    return out


def verify_all(
    bugs: list[tuple[str, str]],
    source_root: Path,
) -> list[tuple[str, str, Verdict]]:
    """
    Run the verifier on each bug, threading previous accepted reports
    so duplicates can be detected.
    """
    previous_accepted: list[str] = []
    out: list[tuple[str, str, Verdict]] = []
    for pid, bug in bugs:
        verdict = verify_bug(
            bug_description=bug,
            source_root=source_root,
            previous_reports=previous_accepted,
        )
        out.append((pid, bug, verdict))
        if verdict.is_real:
            previous_accepted.append(bug)
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="End-to-end demo: 3 personas find bugs, Codex heals verified ones, Maria re-validates."
    )
    parser.add_argument("--target", default="http://localhost:8000")
    parser.add_argument(
        "--sequential",
        action="store_true",
        help="run personas one at a time (slower; cleaner narration)",
    )
    parser.add_argument(
        "--all-headless",
        action="store_true",
        help="run every persona headless (no visible browser)",
    )
    parser.add_argument(
        "--spotlight",
        default="priya",
        help="which persona runs in a visible browser window during discovery "
             "(default: priya - she's the most visually interesting because "
             "she fills a promo code field and completes a checkout). "
             "Other options: kelvin, hassan.",
    )
    parser.add_argument(
        "--revalidator",
        default="kelvin",
        help="which persona runs the post-heal re-validation pass "
             "(default: kelvin - he's good at scrutinising team-page math, "
             "which catches most regressions).",
    )
    parser.add_argument("--max-steps", type=int, default=10)
    parser.add_argument("--max-iterations", type=int, default=10)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--skip-reset", action="store_true")
    parser.add_argument("--no-revalidate", action="store_true")
    parser.add_argument(
        "--no-inspectors",
        action="store_true",
        help="skip backend inspector agents; run browser personas only",
    )
    parser.add_argument(
        "--skip-personas",
        action="store_true",
        help="skip browser personas; useful for deterministic backend-agent smoke tests",
    )
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="stop after discovery and save reports; do not verify or heal",
    )
    parser.add_argument("--max-heals", type=int, default=3, help="cap on heals per run")
    parser.add_argument(
        "--stagger",
        type=float,
        default=15.0,
        help="seconds between non-spotlight persona starts (default 15.0). "
             "Higher values avoid OpenAI per-minute token limits when running "
             "personas in parallel. Set to 0 to disable.",
    )
    args = parser.parse_args()

    overall_started = time.time()

    # -- Stage 0: reset ------------------------------------------------------
    banner("STAGE 0 — RESET TO BUGGY BASELINE")
    if args.skip_reset:
        print("  (skipped — --skip-reset)")
    else:
        ok = reset_prototype_to_baseline()
        if ok:
            print(f"  ✓ Restored {LIVE_MAIN.name} from {BUGGY_BASELINE.name}")
            print(f"  ⚠️  Make sure the prototype server is running with --reload so it sees the changes.")
            print(f"     (cd prototype && uvicorn main:app --reload)")
        else:
            return 2

    # -- Stage 1: discovery (3 personas) ------------------------------------
    banner("STAGE 1 — DISCOVERY: 3 PERSONAS EXPLORE IN PARALLEL")
    print(f"  Spotlight (headed): {args.spotlight}")
    print(f"  Headless: {', '.join(p for p in DISCOVERY_PERSONAS if p != args.spotlight)}")
    print(f"  Max steps per persona: {args.max_steps}")
    print(f"  Mode: {'sequential' if args.sequential else 'parallel'}")
    if not args.sequential and args.stagger > 0:
        print(f"  Stagger: {args.stagger}s between non-spotlight starts")
    print()

    if args.skip_personas:
        reports = {}
        print("  (skipped browser personas â€” --skip-personas)")
    elif args.sequential:
        reports = run_discovery_sequential(
            target_url=args.target,
            max_steps=args.max_steps,
            spotlight_persona_id=args.spotlight,
            all_headless=args.all_headless,
        )
    else:
        reports = asyncio.run(
            run_discovery_parallel(
                target_url=args.target,
                max_steps=args.max_steps,
                spotlight_persona_id=args.spotlight,
                all_headless=args.all_headless,
                stagger_seconds=args.stagger,
            )
        )

    if not args.no_inspectors:
        banner("STAGE 1B â€” BACKEND INSPECTORS: API + AUTH PROBES")
        try:
            inspector_reports = run_backend_inspectors(args.target)
            reports.update(inspector_reports)
            for pid, rpt in inspector_reports.items():
                print(f"  {rpt.persona_name} ({pid}): {len(rpt.possible_bugs)} bug(s) flagged")
                print(f"    {rpt.final_assessment}")
                for bug in rpt.possible_bugs:
                    print(f"    - {bug[:180]}{'...' if len(bug) > 180 else ''}")
        except Exception as e:
            print(f"  âš ï¸  Backend inspectors failed: {type(e).__name__}: {e}")

    print_discovery_summary(reports)

    raw_bugs = aggregate_bugs(reports)
    if args.report_only:
        save_path = PROJECT_ROOT / "personas" / "reports" / f"agent_reports_{int(overall_started)}.json"
        save_path.parent.mkdir(parents=True, exist_ok=True)
        report_payload = {
            "started_at": overall_started,
            "ended_at": time.time(),
            "target": args.target,
            "report_only": True,
            "raw_bug_count": len(raw_bugs),
            "reports": {pid: asdict(rpt) for pid, rpt in reports.items()},
            "raw_bugs": [
                {"persona_id": pid, "bug": bug}
                for pid, bug in raw_bugs
            ],
        }
        save_path.write_text(
            json.dumps(report_payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print()
        print(f"  Report-only mode: saved {len(reports)} agent report(s) to {save_path}")
        print(f"  Raw bugs flagged: {len(raw_bugs)}")
        return 0

    if not raw_bugs:
        print("\n  No possible bugs reported by any persona. Nothing to heal.")
        return 0

    # -- Stage 2: verification ----------------------------------------------
    banner("STAGE 2 — VERIFY: TRIAGE BEFORE HEALING")
    print(f"  Running verifier on {len(raw_bugs)} raw report(s)...")
    print()
    triaged = verify_all(raw_bugs, source_root=PROJECT_ROOT)
    real_bugs: list[tuple[str, str, str | None]] = []
    for pid, bug, verdict in triaged:
        first_line = bug.splitlines()[0][:120]
        if verdict.is_real:
            print(f"  ✓ {pid}: {first_line}")
            print(f"      → {verdict.reasoning}")
            if verdict.suggested_test:
                print(f"      → target test: {verdict.suggested_test}")
            real_bugs.append((pid, bug, verdict.suggested_test))
        elif verdict.verdict == "duplicate":
            print(f"  ⊘ {pid} (DUPLICATE): {first_line}")
            print(f"      → {verdict.reasoning}")
        else:
            print(f"  ⊘ {pid} (NOT A BUG): {first_line}")
            print(f"      → {verdict.reasoning}")

    if not real_bugs:
        print("\n  Verifier rejected every report. Nothing to heal.")
        return 0

    # -- Stage 3: heal each verified bug ------------------------------------
    heal_targets = real_bugs[: args.max_heals]
    banner(f"STAGE 3 — HEAL: CODEX FIXES {len(heal_targets)} VERIFIED BUG(S)")

    heal_results: list[HealResult] = []
    streamer = make_streamer()
    for i, (pid, bug, target_test) in enumerate(heal_targets, 1):
        print(f"\n  Bug {i}/{len(heal_targets)} (from {pid}):")
        for line in bug.splitlines():
            print(f"    {line}")
        if target_test:
            print(f"    [target test: {target_test}]")
        print()
        result = heal(
            bug_description=bug,
            model=args.model,
            max_iterations=args.max_iterations,
            on_event=streamer,
            promote_on_success=True,
            target_test=target_test,
        )
        heal_results.append(result)
        mark = "✓" if result.success else "✗"
        print(f"\n  {mark} Heal {i}: {result.summary} ({result.duration_seconds:.1f}s, {result.iterations} iter)")

    # -- Stage 4: re-validate -----------------------------------------------
    revalidation: PersonaReport | None = None
    revalidation_triage: list[tuple[str, str, Verdict]] = []
    revalidation_real_bugs: list[str] = []

    if not args.no_revalidate:
        banner("STAGE 4 — RE-VALIDATE: KELVIN RE-CHECKS THE SITE")
        persona = get_persona(args.revalidator)
        try:
            revalidation = run_persona(
                persona=persona,
                target_url=args.target,
                max_steps=args.max_steps,
                headless=args.all_headless,
                verbose=True,
            )
        except Exception as e:
            print(f"  ⚠️  Re-validation failed: {type(e).__name__}: {e}")

        if revalidation:
            print()
            print(SUB)
            print(f"  Re-validation - {revalidation.persona_name}")
            print(SUB)
            print(f"  Completed purchase: {revalidation.completed_purchase}")
            print(f"  Final assessment: {revalidation.final_assessment}")

            # Triage the revalidation reports too. After healing, most "still
            # flagged" items tend to be rounding noise or misunderstandings;
            # only verifier-real bugs should count as regressions.
            if revalidation.possible_bugs:
                print(f"\n  Triaging {len(revalidation.possible_bugs)} report(s) post-heal...")
                bugs_to_verify = [(args.revalidator, b) for b in revalidation.possible_bugs]
                revalidation_triage = verify_all(bugs_to_verify, source_root=PROJECT_ROOT)
                for pid, bug, verdict in revalidation_triage:
                    first_line = bug.splitlines()[0][:120]
                    if verdict.is_real:
                        print(f"    ✓ REGRESSION: {first_line}")
                        print(f"        → {verdict.reasoning}")
                        revalidation_real_bugs.append(bug)
                    elif verdict.verdict == "duplicate":
                        print(f"    ⊘ duplicate: {first_line}")
                    else:
                        print(f"    ⊘ not a real bug (likely confusion): {first_line}")
                        print(f"        → {verdict.reasoning}")

                if not revalidation_real_bugs:
                    print("\n  ✅ All revalidation reports were noise/duplicates. No real regressions.")
            else:
                print("\n  ✅ No bugs flagged on re-validation.")

    # -- Summary ------------------------------------------------------------
    overall_duration = time.time() - overall_started
    banner("FINAL SUMMARY", char="=")
    print(f"  Total wall time:        {overall_duration:.1f}s")
    print(f"  Personas run:           {len(reports)}")
    print(f"  Raw reports:            {len(raw_bugs)}")
    print(f"  Verified real bugs:     {len(real_bugs)}")
    print(f"  Bugs healed by Codex:   {sum(1 for r in heal_results if r.success)}")
    print(f"  Bugs that failed heal:  {sum(1 for r in heal_results if not r.success)}")
    if revalidation:
        n = len(revalidation_real_bugs)
        raw = len(revalidation.possible_bugs)
        if n == 0:
            print(f"  Re-validation:          ✅ clean ({raw} raw report(s), 0 verified regressions)")
        else:
            print(f"  Re-validation:          ⚠️  {n} verified regression(s) of {raw} raw")
    print()
    print("  Heal timeline:")
    for i, r in enumerate(heal_results, 1):
        mark = "✓" if r.success else "✗"
        files = ", ".join(r.modified_files) if r.modified_files else "(none)"
        print(f"    [{i}] {mark} {r.duration_seconds:>5.1f}s — {files}")
    print(BAR)

    # Save full transcript for the dashboard
    save_path = PROJECT_ROOT / "personas" / "reports" / f"full_loop_{int(overall_started)}.json"
    save_path.parent.mkdir(parents=True, exist_ok=True)

    def _serialize_heal(r: HealResult) -> dict:
        # Include the per-tool-call events so the dashboard can replay them.
        # We keep diffs (they're the visual hero) and trim result payloads.
        return {
            "success": r.success,
            "summary": r.summary,
            "bug_description": r.bug_description,
            "duration_seconds": r.duration_seconds,
            "iterations": r.iterations,
            "model_used": r.model_used,
            "modified_files": r.modified_files,
            "final_test_passed": r.final_test_passed,
            "error": r.error,
            "started_at": r.started_at,
            "finished_at": r.finished_at,
            "events": [
                {
                    "iteration": ev.iteration,
                    "name": ev.name,
                    "arguments_preview": _trim(ev.arguments),
                    "result_preview": _trim(ev.result),
                    "diff": ev.diff,
                }
                for ev in r.events
            ],
        }

    transcript = {
        "started_at": overall_started,
        "ended_at": time.time(),
        "target": args.target,
        "spotlight": args.spotlight,
        "revalidator": args.revalidator,
        "discovery": {pid: asdict(rpt) for pid, rpt in reports.items()},
        "triage": [
            {
                "persona_id": pid,
                "bug": bug,
                "verdict": v.verdict,
                "reasoning": v.reasoning,
                "duplicate_of": v.duplicate_of,
            }
            for (pid, bug, v) in triaged
        ],
        "heals": [_serialize_heal(r) for r in heal_results],
        "revalidation": asdict(revalidation) if revalidation else None,
        "revalidation_triage": [
            {
                "persona_id": pid,
                "bug": bug,
                "verdict": v.verdict,
                "reasoning": v.reasoning,
                "duplicate_of": v.duplicate_of,
            }
            for (pid, bug, v) in revalidation_triage
        ],
        "revalidation_real_regressions": revalidation_real_bugs,
    }
    save_path.write_text(json.dumps(transcript, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  Full transcript: {save_path}")
    print(BAR)

    if any(not r.success for r in heal_results):
        return 1
    if revalidation and revalidation_real_bugs:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
