"""
heal.py — CLI entrypoint for the self-healing orchestrator.

Usage:
    python -m orchestrator.heal --bug "Your bug description here"
    python -m orchestrator.heal --bug-file path/to/persona_report.json
    python -m orchestrator.heal --bug "..." --dry-run     # don't promote
    python -m orchestrator.heal --bug "..." --model gpt-5.5

Run from the project root so the sandbox can find the source files.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

# Make orchestrator importable when run as script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

load_dotenv()

from orchestrator.agent import heal, DEFAULT_MODEL  # noqa: E402
from orchestrator.tools import ToolEvent  # noqa: E402


# ---------------------------------------------------------------------------
# Pretty stdout streaming
# ---------------------------------------------------------------------------

def _truncate(s: str, n: int = 200) -> str:
    s = str(s)
    return s if len(s) <= n else s[: n - 3] + "..."


def make_streamer():
    """Return an on_event callback that prints a live trace to stdout."""

    def stream(ev: ToolEvent):
        prefix = f"  [{ev.iteration:>2}] {ev.name}"
        if ev.name == "read_file":
            print(f"{prefix}({ev.arguments.get('path')})")
            err = ev.result.get("error")
            if err:
                print(f"       ⚠️  {err}")
            else:
                print(f"       {ev.result.get('line_count', 0)} lines read")

        elif ev.name == "list_files":
            print(f"{prefix}({ev.arguments.get('subdir')}, {ev.arguments.get('pattern', '*')})")
            print(f"       {ev.result.get('total', 0)} files found")

        elif ev.name == "write_file":
            path = ev.arguments.get("path", "?")
            changed = ev.result.get("lines_changed", "?")
            print(f"{prefix}({path}) — {changed} changed lines")
            if ev.diff:
                # Show first ~20 lines of the diff
                diff_lines = ev.diff.splitlines()
                preview = diff_lines[:20]
                for line in preview:
                    if line.startswith("+") and not line.startswith("+++"):
                        print(f"       \033[92m{line}\033[0m")  # green
                    elif line.startswith("-") and not line.startswith("---"):
                        print(f"       \033[91m{line}\033[0m")  # red
                    elif line.startswith("@@"):
                        print(f"       \033[96m{line}\033[0m")  # cyan
                    else:
                        print(f"       {line}")
                if len(diff_lines) > 20:
                    print(f"       ... ({len(diff_lines) - 20} more lines)")

        elif ev.name == "run_tests":
            print(f"{prefix}({ev.arguments.get('test_path', 'tests/')})")
            passed = ev.result.get("passed")
            mark = "✓" if passed else "✗"
            color = "\033[92m" if passed else "\033[91m"
            print(f"       {color}{mark} {ev.result.get('summary', '')}\033[0m")
            if not passed:
                tail = ev.result.get("stdout_tail", "")
                # Show last 12 lines of pytest output on failure
                for line in tail.splitlines()[-12:]:
                    print(f"         {line}")

        elif ev.name == "done":
            print(f"{prefix}: {ev.arguments.get('summary')}")
            mods = ev.arguments.get("modified_files") or []
            for p in mods:
                print(f"       modified: {p}")

        else:
            print(f"{prefix} -> {_truncate(ev.result)}")

    return stream


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Run the self-healing orchestrator on a bug.")
    bug_src = parser.add_mutually_exclusive_group(required=True)
    bug_src.add_argument("--bug", help="bug description in plain text")
    bug_src.add_argument(
        "--bug-file",
        help="path to a persona report JSON; uses its 'possible_bugs' field",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"OpenAI model (default: {DEFAULT_MODEL}, falls back to gpt-5.5)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="don't promote changes to live source, even on success",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=10,
        help="cap on tool-call iterations",
    )
    args = parser.parse_args()

    if args.bug_file:
        report = json.loads(Path(args.bug_file).read_text(encoding="utf-8"))
        bugs = report.get("possible_bugs") or []
        if not bugs:
            print("No possible_bugs found in report.", file=sys.stderr)
            sys.exit(2)
        # Concatenate them so Codex gets the full picture
        bug_description = "\n".join(f"- {b}" for b in bugs)
        print(f"=== From persona {report.get('persona_name', '?')} ===")
    else:
        bug_description = args.bug

    print("\n" + "=" * 72)
    print("  CODEX SELF-HEALING ORCHESTRATOR")
    print("=" * 72)
    print(f"  Model: {args.model}")
    print(f"  Bug:")
    for line in bug_description.splitlines():
        print(f"    {line}")
    print(f"  Dry-run: {args.dry_run}")
    print("=" * 72 + "\n")

    result = heal(
        bug_description=bug_description,
        model=args.model,
        max_iterations=args.max_iterations,
        on_event=make_streamer(),
        promote_on_success=not args.dry_run,
    )

    print("\n" + "=" * 72)
    if result.success:
        print(f"  ✓ HEAL SUCCESSFUL ({result.duration_seconds:.1f}s, {result.iterations} iterations)")
    else:
        print(f"  ✗ HEAL FAILED ({result.duration_seconds:.1f}s, {result.iterations} iterations)")
    print("=" * 72)
    print(f"  Summary: {result.summary}")
    if result.modified_files:
        print(f"  Modified files: {', '.join(result.modified_files)}")
    print(f"  Final test passed: {result.final_test_passed}")
    if result.error:
        print(f"  Error: {result.error}")
    print("=" * 72)

    sys.exit(0 if result.success else 1)


if __name__ == "__main__":
    main()
