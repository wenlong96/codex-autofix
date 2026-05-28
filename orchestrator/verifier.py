"""
verifier.py — Pre-heal triage step.

Before spending tokens on a full heal loop, Codex reads the relevant source
and decides: is this report a real bug, or a misunderstanding by the reporter?

Why this matters:
  - Personas can flag things that aren't actually bugs ("I clicked Buy Solo
    and an order was placed without me confirming" — that IS the confirm).
  - Personas can duplicate-flag the same bug observed on different products.
  - Without a verification gate, Codex sometimes invents phantom fixes for
    non-bugs (modifying app.js to re-derive a value that was already correct).

The verifier produces a small structured verdict that the orchestrator uses
to decide whether to proceed with the heal.

Verdict shape:
  {
    "verdict": "real" | "misunderstanding" | "duplicate",
    "reasoning": "1-3 sentences explaining the call",
    "suggested_fix_location": "prototype/main.py:join_team or similar — only if real",
    "duplicate_of": "the previous report it duplicates — only if duplicate"
  }
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openai import OpenAI

from .sandbox import Sandbox


VERIFIER_MODEL = "gpt-5.5"  # cheaper than codex; this is triage, not coding
DEFAULT_MAX_FILES_TO_READ = 3


@dataclass
class Verdict:
    verdict: str  # "real" | "misunderstanding" | "duplicate"
    reasoning: str
    suggested_fix_location: str | None = None
    suggested_test: str | None = None  # e.g. "test_promo_save10_reduces_total"
    duplicate_of: str | None = None
    elapsed_seconds: float = 0.0

    @property
    def is_real(self) -> bool:
        return self.verdict == "real"

    def __str__(self) -> str:
        if self.verdict == "real":
            return f"✓ REAL BUG ({self.elapsed_seconds:.1f}s): {self.reasoning}"
        if self.verdict == "duplicate":
            return f"⊘ DUPLICATE of \"{self.duplicate_of}\" ({self.elapsed_seconds:.1f}s): {self.reasoning}"
        return f"⊘ MISUNDERSTANDING ({self.elapsed_seconds:.1f}s): {self.reasoning}"


VERIFIER_SYSTEM_PROMPT = """You are a senior engineer triaging incoming bug \
reports from end-users. You receive:
  1. A bug report (in the user's own words)
  2. The contents of likely-relevant source files
  3. Optionally, previous bug reports already verified or healed in this session

Your job: classify the report into exactly one of:
  - "real": the code has the bug the user described. Worth fixing.
  - "misunderstanding": the user described something that looks buggy but
    the code is correct. Maybe they were confused by the UX, or they
    misread numbers, or they're describing intended behaviour, or the
    discrepancy is a normal floating-point rounding artifact.
  - "duplicate": the same underlying bug as one already in the list of
    previous reports. Don't fix it again.

Specific guidance:
  - Rounding/precision artifacts of LESS THAN 2 CENTS (e.g. S$13.48 vs
    S$13.49, S$3.67 vs S$3.68) are EXPECTED behaviour of floating-point
    arithmetic combined with currency formatting. These are
    "misunderstanding", NEVER "real". Do not classify them as bugs even
    if the user is confident.
  - Be strict. If there's any doubt that this is a real bug in the code,
    lean toward "misunderstanding". A phantom fix is worse than a missed
    bug because a phantom fix is a regression in disguise.
  - SELF-CONSISTENCY: Before returning, re-read your `reasoning`. If your
    reasoning EXPLAINS why the discrepancy is expected/intended (e.g.
    "it's normal rounding"), the verdict MUST be "misunderstanding". Your
    reasoning and verdict must agree.

Return ONLY a JSON object with this shape:
{
  "verdict": "real" | "misunderstanding" | "duplicate",
  "reasoning": "1-2 sentences",
  "suggested_fix_location": "e.g. 'prototype/main.py - join_team()'",
  "suggested_test": "the name of the test function in test_regressions.py that covers this behaviour, e.g. 'test_promo_save10_reduces_total'. Look at the provided test file and pick the single most relevant test. null if none clearly matches.",
  "duplicate_of": "verbatim quote of the previous report this matches (only if duplicate)"
}"""


def verify_bug(
    bug_description: str,
    source_root: Path,
    previous_reports: list[str] | None = None,
    client: OpenAI | None = None,
) -> Verdict:
    """
    Verify a bug report against the live source.

    Reads a small set of files (main.py + tests) to give the model context,
    then asks for a verdict.
    """
    started = time.time()
    client = client or OpenAI()
    previous_reports = previous_reports or []

    # Read a small set of source files the verifier needs
    candidate_files = [
        "prototype/main.py",
        "prototype/tests/test_regressions.py",
        "prototype/static/app.js",
    ]
    file_contents: list[str] = []
    for rel in candidate_files[:DEFAULT_MAX_FILES_TO_READ]:
        f = source_root / rel
        if f.exists():
            try:
                content = f.read_text(encoding="utf-8")
                file_contents.append(f"--- FILE: {rel} ---\n{content}")
            except Exception:
                pass

    code_block = "\n\n".join(file_contents)

    prev_block = ""
    if previous_reports:
        prev_block = (
            "\n\nPREVIOUS REPORTS IN THIS SESSION (already classified):\n"
            + "\n".join(f"- {r}" for r in previous_reports)
        )

    user_msg = (
        f"BUG REPORT:\n{bug_description}\n\n"
        f"RELEVANT SOURCE FILES:\n{code_block}"
        f"{prev_block}\n\n"
        "Classify this report. Return only the JSON verdict."
    )

    try:
        resp = client.responses.create(
            model=VERIFIER_MODEL,
            input=[
                {"role": "system", "content": VERIFIER_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
        )
        text = _extract_output_text(resp)
        data = _parse_json(text)
    except Exception as e:
        # Fail open: if the verifier itself errors, treat the report as real
        # so we don't accidentally block legitimate heals.
        return Verdict(
            verdict="real",
            reasoning=f"Verifier failed ({type(e).__name__}); defaulting to real.",
            elapsed_seconds=time.time() - started,
        )

    verdict_str = (data.get("verdict") or "real").lower().strip()
    if verdict_str not in {"real", "misunderstanding", "duplicate"}:
        verdict_str = "real"

    return Verdict(
        verdict=verdict_str,
        reasoning=data.get("reasoning", "")[:500],
        suggested_fix_location=data.get("suggested_fix_location"),
        suggested_test=data.get("suggested_test"),
        duplicate_of=data.get("duplicate_of"),
        elapsed_seconds=time.time() - started,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_output_text(resp: Any) -> str:
    """Pull plain text from a Responses API result."""
    # The SDK exposes .output_text on most response objects
    text = getattr(resp, "output_text", None)
    if text:
        return text
    # Fallback: walk the output items
    parts: list[str] = []
    for item in getattr(resp, "output", []) or []:
        if getattr(item, "type", None) == "message":
            for content in getattr(item, "content", []) or []:
                t = getattr(content, "text", None)
                if t:
                    parts.append(t)
    return "\n".join(parts)


def _parse_json(text: str) -> dict:
    """Tolerant JSON parsing — strips code fences if present."""
    s = text.strip()
    if s.startswith("```"):
        s = s.split("```", 2)[1]
        if s.startswith("json"):
            s = s[4:]
        s = s.strip().rstrip("`").strip()
    return json.loads(s)
