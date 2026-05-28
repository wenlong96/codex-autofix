"""
Codex agent loop — Responses API.

Uses gpt-5-codex (Responses-API-only model) for agentic coding. Threads state
across turns via `previous_response_id` so we don't re-send the full message
history each iteration — token-efficient and supports long chains of tool calls.

Workflow:
    bug_description -> Codex (loop) -> tool calls -> sandbox -> tests
                                                              \\-> promote_to_live

The agent only operates on the sandbox. Promotion to live happens OUTSIDE the
agent loop, gated on `done` + tests passing. That's the safety boundary.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from openai import OpenAI

from .sandbox import Sandbox
from .tools import TOOL_SCHEMAS, ToolEvent, ToolExecutor


# gpt-5-codex is Responses-API-only and purpose-built for agentic coding.
# Fallback to gpt-5.5 (also Responses-API-compatible) if codex access fails.
DEFAULT_MODEL = os.environ.get("CODEX_MODEL", "gpt-5-codex")
FALLBACK_MODEL = "gpt-5.5"
MAX_ITERATIONS = 12


SYSTEM_PROMPT = """You are a senior backend engineer fixing a bug in a small \
e-commerce service. You have tools to read files, list directories, write \
files (full content replacement), and run pytest. Work entirely inside a \
sandboxed copy of the project. Your changes do not touch production until \
tests pass and a human approves.

Project structure:
  - prototype/main.py            FastAPI backend, all routes
  - prototype/seed.py            DB seed script
  - prototype/tests/             pytest suite including regression tests for known bugs
  - prototype/static/            frontend (vanilla JS, only relevant if bug is UI-related)

Methodology:
  1. Start by listing files to orient yourself, then read the relevant code.
  2. Understand the bug before writing any patch. Look at the relevant test if there is one.
  3. Apply the smallest possible fix. Do NOT rewrite or restructure unrelated code.
  4. After write_file, ALWAYS run_tests to verify your fix.
  5. If tests fail, read the failure carefully and iterate.
  6. When all relevant tests pass, call done() with a one-line summary.

CRITICAL RULES (violating these wastes your iteration budget):
  - The bug is almost always in CODE, not in comments or docstrings. Do NOT
    edit the module-level docstring or comments unless the bug is literally
    inside them.
  - PRESERVE every character in the source file VERBATIM except the lines
    you are deliberately changing for the fix. Do not normalise unicode,
    rewrite punctuation, swap em-dashes for hyphens, replace ✓/✅/← with
    numbers or text, or "tidy" anything. If a character looks unusual to
    you, KEEP IT EXACTLY AS IS. Test files and the prototype intentionally
    contain non-ASCII characters that must survive round-trips.
  - If you call write_file and tests still fail, the next write_file MUST
    change DIFFERENT lines than the previous one. Do not retry the same
    cosmetic edit hoping it sticks.
  - When fixing one bug, do NOT change code that is unrelated to that bug.
    If a test for bug N keeps failing, the fix is in code for bug N - not
    in a different file or a different function.
  - Run the SPECIFIC failing test (e.g. tests/test_regressions.py::test_promo_save10_reduces_total)
    not the whole suite, so you get focused feedback.
  - You are fixing exactly ONE bug. The test suite contains tests for OTHER
    bugs that are being fixed separately — those tests WILL still fail and
    that is expected and fine. Do not try to fix them. The moment the test
    for YOUR bug passes, call done() immediately. Do not re-run the full
    suite "to be sure" — that wastes iterations and the other failures will
    mislead you.
  - write_file requires the COMPLETE new file content, not just changed lines.
  - You have a limit of about 12 tool calls. Use them wisely — a typical fix
    needs only: list, read, write, run one test, done.
"""


@dataclass
class HealResult:
    success: bool
    summary: str
    bug_description: str
    iterations: int
    model_used: str = ""
    events: list[ToolEvent] = field(default_factory=list)
    modified_files: list[str] = field(default_factory=list)
    final_test_passed: bool = False
    error: str | None = None
    started_at: float = 0.0
    finished_at: float = 0.0

    @property
    def duration_seconds(self) -> float:
        return self.finished_at - self.started_at

    def diffs(self) -> dict[str, str]:
        """Map of path -> latest diff for that file."""
        out: dict[str, str] = {}
        for ev in self.events:
            if ev.name == "write_file" and ev.diff:
                out[ev.arguments.get("path", "?")] = ev.diff
        return out


def heal(
    bug_description: str,
    source_root: Path | None = None,
    model: str = DEFAULT_MODEL,
    max_iterations: int = MAX_ITERATIONS,
    on_event: Callable[[ToolEvent], None] | None = None,
    promote_on_success: bool = True,
    target_test: str | None = None,
) -> HealResult:
    """
    Run the Codex healing loop for a given bug.

    `target_test` (optional): the specific failing test that covers this bug,
    e.g. "test_promo_save10_reduces_total". When provided, Codex is told to
    target ONLY that test and ignore other suite failures (which belong to
    other bugs handled by other heal calls). This prevents Codex from burning
    iterations re-running the full suite and never calling done().
    """
    started = time.time()
    if source_root is None:
        source_root = Path(__file__).resolve().parent.parent

    client = OpenAI()

    sandbox = Sandbox.create(source_root=source_root)
    executor = ToolExecutor(sandbox=sandbox)

    events: list[ToolEvent] = []
    modified_files: set[str] = set()
    done_summary = ""
    last_test_passed = False
    error: str | None = None
    iterations = 0
    model_used = model

    # User prompt — initial bug report
    if target_test:
        test_guidance = (
            f"\n\nThe specific failing test that covers this bug is:\n"
            f"    tests/{target_test}\n"
            "Run ONLY that test to check your fix (use its full path, e.g. "
            f"tests/test_regressions.py::{target_test}). Other tests in the "
            "suite cover DIFFERENT bugs that are being fixed separately — they "
            "are NOT your responsibility and WILL still fail. Do not run the "
            "whole suite. The moment YOUR test passes, call done() immediately "
            "with a one-line summary. Do not keep exploring after your test is "
            "green."
        )
    else:
        test_guidance = (
            "\n\nThere is a regression test in tests/test_regressions.py that "
            "covers this behaviour. Find it, run only that test to verify your "
            "fix, and call done() as soon as it passes. Other tests in the "
            "suite may cover unrelated bugs and can still fail — ignore them."
        )

    user_prompt = (
        "A bug has been reported in the prototype service. Please diagnose "
        "and fix it.\n\n"
        f"Bug description:\n{bug_description}"
        f"{test_guidance}\n\n"
        "Start by orienting yourself with list_files and reading the "
        "relevant source."
    )

    previous_response_id: str | None = None
    # For the first call we send the system prompt + user prompt as input.
    # For subsequent calls we send only the function_call_output items,
    # threading state via previous_response_id.
    initial_input: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
    next_input: list[dict] | None = initial_input

    try:
        for iteration in range(1, max_iterations + 1):
            iterations = iteration

            response, model_used = _call_responses_with_fallback(
                client=client,
                model=model_used,
                input_items=next_input or [],
                previous_response_id=previous_response_id,
                tools=TOOL_SCHEMAS,
            )

            previous_response_id = response.id

            # Collect function_call items from the response output
            function_calls = [
                item for item in response.output
                if getattr(item, "type", None) == "function_call"
            ]

            if not function_calls:
                # Codex produced text only (probably asking a question or
                # claiming completion without calling done). Nudge it.
                if iteration < max_iterations:
                    next_input = [
                        {
                            "role": "user",
                            "content": (
                                "Please continue with a tool call. If you "
                                "believe the fix is complete, call the done "
                                "tool with a summary."
                            ),
                        }
                    ]
                    continue
                else:
                    break

            # Execute each function call and collect outputs for next turn
            tool_outputs: list[dict] = []
            should_stop = False

            for fc in function_calls:
                name = fc.name
                call_id = fc.call_id
                try:
                    arguments = json.loads(fc.arguments or "{}")
                except json.JSONDecodeError:
                    arguments = {}

                result, diff = executor.execute(name, arguments)

                event = ToolEvent(
                    iteration=iteration,
                    name=name,
                    arguments=arguments,
                    result=result,
                    diff=diff,
                )
                events.append(event)
                if on_event is not None:
                    try:
                        on_event(event)
                    except Exception:
                        pass

                if name == "write_file":
                    modified_files.add(arguments.get("path", ""))
                if name == "run_tests":
                    last_test_passed = bool(result.get("passed"))
                if name == "done":
                    done_summary = arguments.get("summary", "")
                    for p in arguments.get("modified_files", []) or []:
                        modified_files.add(p)
                    should_stop = True

                tool_outputs.append(
                    {
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": json.dumps(result),
                    }
                )

            if should_stop:
                break

            # Detect "same file written twice in a row with low line-change count"
            # — that's the docstring-loop failure mode. Nudge Codex to change
            # different lines.
            nudge_msg = _detect_unproductive_loop(events)
            if nudge_msg:
                tool_outputs.append(
                    {
                        "role": "user",
                        "content": nudge_msg,
                    }
                )

            next_input = tool_outputs

    except Exception as e:
        error = f"{type(e).__name__}: {e}"

    finally:
        promoted_count = 0
        if (
            promote_on_success
            and done_summary
            and last_test_passed
            and error is None
        ):
            for path in modified_files:
                try:
                    sandbox.promote_file(path)
                    promoted_count += 1
                except Exception as e:
                    error = f"Promotion failed for {path}: {e}"
                    break

        sandbox.cleanup()

    success = bool(done_summary and last_test_passed and error is None)
    return HealResult(
        success=success,
        summary=done_summary or ("FAILED: " + (error or "no done signal")),
        bug_description=bug_description,
        iterations=iterations,
        model_used=model_used,
        events=events,
        modified_files=sorted(modified_files),
        final_test_passed=last_test_passed,
        error=error,
        started_at=started,
        finished_at=time.time(),
    )


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _call_responses_with_fallback(
    client: OpenAI,
    model: str,
    input_items: list[dict],
    previous_response_id: str | None,
    tools: list[dict],
):
    """
    Call client.responses.create with fallback to gpt-5.5 on model-access errors.
    Returns (response, effective_model_used).
    """
    kwargs: dict[str, Any] = {
        "model": model,
        "input": input_items,
        "tools": tools,
    }
    if previous_response_id is not None:
        kwargs["previous_response_id"] = previous_response_id

    try:
        return client.responses.create(**kwargs), model
    except Exception as e:
        msg = str(e).lower()
        compat_error = (
            ("not found" in msg)
            or ("does not exist" in msg)
            or ("permission" in msg)
            or ("do not have access" in msg)
            or ("unsupported_model" in msg)
        )
        if model != FALLBACK_MODEL and compat_error:
            print(
                f"  [model fallback] {model} unavailable, "
                f"retrying with {FALLBACK_MODEL}"
            )
            kwargs["model"] = FALLBACK_MODEL
            return client.responses.create(**kwargs), FALLBACK_MODEL
        raise


def _detect_unproductive_loop(events: list[ToolEvent]) -> str | None:
    """
    Look at the most recent events and return a nudge message if Codex is in
    an unproductive loop, otherwise None.

    Two patterns we catch:
      1. Two write_file calls to the same path in a row, both with low
         line-change counts (likely cosmetic docstring/comment edits).
      2. A write_file followed by a failing run_tests, then another write_file
         to the same path with similar diff size — same-edit retry.
    """
    writes = [e for e in events if e.name == "write_file"]
    if len(writes) < 2:
        return None

    last = writes[-1]
    prev = writes[-2]
    if last.arguments.get("path") != prev.arguments.get("path"):
        return None

    last_lines = last.result.get("lines_changed", 0)
    prev_lines = prev.result.get("lines_changed", 0)

    # Heuristic: both writes touch <= 10 lines AND both diffs look similar
    if last_lines > 10 or prev_lines > 10:
        return None

    # Compare the diff regions roughly — if first 4 changed-line prefixes are
    # identical, it's almost certainly the same kind of edit
    def _key_lines(diff: str | None, n: int = 4) -> list[str]:
        if not diff:
            return []
        out: list[str] = []
        for line in diff.splitlines():
            if line.startswith(("+", "-")) and not line.startswith(("+++", "---")):
                out.append(line[:60])
                if len(out) >= n:
                    break
        return out

    if _key_lines(last.diff) == _key_lines(prev.diff):
        return (
            "STOP. Your last two write_file calls targeted the same file with "
            "very similar diffs and the bug is still not fixed. The fix is "
            "almost certainly NOT in the lines you keep editing. Re-read the "
            "relevant test failure and edit different lines this time. The "
            "module docstring and comments are NOT where the bug lives."
        )
    return None
