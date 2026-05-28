"""
Run a persona end-to-end against the prototype.

Two interfaces:
  - run_persona(...)        — synchronous (backwards compat). Used by the
                              CLI in __main__ block: `python run_one.py --persona maria`.
  - run_persona_async(...)  — async version. Used by full_loop to run multiple
                              personas in parallel via asyncio.gather().

Both share the same prompts, action schema, and report format.

Set LLM_PROVIDER=gemini (default) or openai in .env.

Output:
    - Console: live narration of what the persona is doing
    - reports/<persona_id>_<timestamp>.json: full structured report
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# Make `personas` package importable when running directly
sys.path.insert(0, str(Path(__file__).parent))

from llm_client import get_llm_client  # noqa: E402
from persona_profiles import Persona, get_persona  # noqa: E402

load_dotenv()


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

@dataclass
class Observation:
    step: int
    page_url: str
    persona_thought: str
    action_taken: dict
    friction_noted: str | None = None


@dataclass
class PersonaReport:
    persona_id: str
    persona_name: str
    target_url: str
    started_at: float
    finished_at: float
    completed_purchase: bool
    final_assessment: str
    friction_points: list[str] = field(default_factory=list)
    possible_bugs: list[str] = field(default_factory=list)
    observations: list[Observation] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

ACTION_SCHEMA = """Return a JSON object with these fields:
{
  "thought": "1-2 sentences in character explaining what you're thinking",
  "friction": "if something on this page bothered, confused, or surprised you, describe it in one sentence. otherwise null.",
  "action": {
    "type": "click" | "fill" | "navigate" | "done",
    // For "click": text MUST be the visible button/link text, copied as-is
    // from the screenshot. Prefer SHORTER unique substrings over the full
    // label. For example, click "Buy solo" (NOT "Buy solo (S$89.90)"),
    // click "Start a team" (NOT "Start a team for this product").
    // Long labels with prices, parentheses or punctuation often fail to
    // match the rendered DOM exactly. Keep clicks to the verb + noun.
    // ONLY click things that are clearly clickable: buttons, links.
    // Plain text/labels are NOT clickable.
    "text": "short visible text of the button/link to click",
    // for "fill": which field and what value
    "selector": "CSS selector or name attribute",
    "value": "what to type",
    // for "navigate": the URL/path to go to
    "url": "/some/path",
    // for "done": why you're finished
    "reason": "e.g. 'completed purchase' or 'gave up because X'"
  }
}

Return ONLY the JSON. No prose."""


def build_action_system_prompt(persona: Persona, goal: str) -> str:
    return f"""{persona.to_prompt_block()}

Your shopping goal right now:
{goal}

You're looking at a screenshot of a web page. Decide your next single action.

You have a limited number of steps available. Be efficient — don't keep
revisiting the same page over and over. If something didn't work the first
time, try a DIFFERENT approach, not the same one again. If your goal is
already accomplished or impossible, call "done".

{ACTION_SCHEMA}"""


def build_report_system_prompt(persona: Persona) -> str:
    return f"""{persona.to_prompt_block()}

You just finished a shopping session. Write an honest debrief.

Return a JSON object:
{{
  "completed_purchase": true/false,
  "final_assessment": "2-3 sentences. Would you actually buy from this site? What stood out — good or bad?",
  "friction_points": ["specific UX issues you hit, one per item"],
  "possible_bugs": ["anything that looked wrong/broken/sketchy. Be specific. Only flag things that are ACTUAL bugs in the system — wrong math, errors, broken endpoints. Do NOT flag things you simply found confusing, or your own actions."]
}}

Return ONLY the JSON."""


# ---------------------------------------------------------------------------
# Shared per-step LLM call (used by both sync and async paths)
# ---------------------------------------------------------------------------

DEFAULT_GOAL = (
    "Browse the site. Find a product you might buy. If there's a team-purchase "
    "discount, decide whether it's worth it for you. Try to complete a purchase "
    "if it makes sense. Be your honest self — if something feels off, note it."
)

MAX_STEPS = 10


def _summarize_action_for_memory(action: dict) -> str:
    """One-line summary of an action, for the recent-actions memory buffer."""
    atype = action.get("type", "?")
    if atype == "click":
        return f"click '{action.get('text', '')}'"
    if atype == "fill":
        return f"fill {action.get('selector', '')} with '{action.get('value', '')}'"
    if atype == "navigate":
        return f"navigate to {action.get('url', '')}"
    if atype == "done":
        return f"done: {action.get('reason', '')}"
    return atype


def _decide_next_action(
    llm,
    persona: Persona,
    goal: str,
    screenshot: bytes,
    recent_actions: list[str] | None = None,
) -> dict:
    """Single LLM round trip — what should the persona do next?

    `recent_actions` is a list of short summaries of recent actions (the last
    3-5 steps). Including this in the prompt prevents the persona from looping
    on the same clicks repeatedly when something didn't work the first time.
    """
    memory_block = ""
    if recent_actions:
        memory_block = (
            "\n\nYour most recent actions (oldest → newest):\n"
            + "\n".join(f"  {i+1}. {a}" for i, a in enumerate(recent_actions))
            + "\n\nIf you're about to repeat one of these actions, STOP and try "
            "something genuinely different — a different button, a different page, "
            "or call done."
        )

    return llm.complete_json(
        system=build_action_system_prompt(persona, goal),
        user=f"What's your next action?{memory_block}",
        image_bytes=screenshot,
        image_mime="image/png",
        temperature=0.4,
    )


def _build_final_report(
    llm,
    persona: Persona,
    observations: list[Observation],
    completed: bool,
) -> dict:
    """Single LLM round trip — debrief at the end of the session."""
    history_summary = json.dumps(
        [
            {
                "step": o.step,
                "url": o.page_url,
                "thought": o.persona_thought,
                "action": o.action_taken,
                "friction": o.friction_noted,
            }
            for o in observations
        ],
        indent=2,
    )
    try:
        return llm.complete_json(
            system=build_report_system_prompt(persona),
            user=f"Here's everything you did and noticed:\n\n{history_summary}\n\nNow write your debrief.",
            temperature=0.4,
            max_tokens=1500,
        )
    except Exception as e:
        return {
            "completed_purchase": completed,
            "final_assessment": f"Report generation failed: {e}",
            "friction_points": [],
            "possible_bugs": [],
        }


def _click_candidates(text: str) -> list[str]:
    """
    Generate fallback candidates for clicking, ordered from most-specific to
    least-specific. Personas frequently paraphrase button text (drop the 'S$'
    prefix, omit punctuation, simplify whitespace) which causes Playwright's
    text matcher to time out. We try increasingly forgiving variants until
    one of them lands.

    Example: "Buy solo ($89.90)" yields:
       1. "Buy solo ($89.90)"     (literal as given)
       2. "Buy solo"              (parenthetical stripped)
       3. "Buy"                   (first word)
    """
    text = (text or "").strip()
    if not text:
        return []
    candidates: list[str] = [text]

    # 1. Strip parenthetical content: "Buy solo ($89.90)" -> "Buy solo"
    import re
    no_paren = re.sub(r"\s*\([^)]*\)\s*", " ", text).strip()
    if no_paren and no_paren != text:
        candidates.append(no_paren)

    # 2. Strip trailing punctuation: "Start a team." -> "Start a team"
    no_punct = re.sub(r"[\.!?:;,]+$", "", no_paren or text).strip()
    if no_punct and no_punct not in candidates:
        candidates.append(no_punct)

    # 3. First few significant words, capped at 3, only if more than one word.
    #    Skip if the result is too short to be a useful match.
    words = (no_punct or text).split()
    if len(words) > 1:
        prefix = " ".join(words[:3]).strip()
        if prefix and prefix not in candidates and len(prefix) >= 3:
            candidates.append(prefix)

    return candidates


def _execute_sync_action(page, action: dict, target_url: str) -> bool:
    """Apply a chosen action against a sync Playwright page. Returns True if done."""
    atype = action.get("type")
    if atype == "done":
        return True
    try:
        if atype == "click":
            text = action.get("text", "")
            last_err: Exception | None = None
            for i, candidate in enumerate(_click_candidates(text)):
                # Shorter timeout on early attempts so we fail-fast to the
                # next fallback; longer timeout on the final one.
                timeout = 1500 if i < 2 else 3000
                try:
                    page.get_by_text(candidate, exact=False).first.click(
                        timeout=timeout
                    )
                    if i > 0:
                        print(f"  (fallback matched on '{candidate}')")
                    return False  # success path; not done
                except Exception as e:
                    last_err = e
            if last_err:
                raise last_err
        elif atype == "fill":
            sel = action.get("selector", "")
            val = action.get("value", "")
            page.locator(sel).fill(val, timeout=5000)
        elif atype == "navigate":
            url = action.get("url", "")
            if url.startswith("/"):
                url = target_url.rstrip("/") + url
            page.goto(url)
    except Exception as e:
        print(f"  [Action failed: {e}]")
    return False


async def _execute_async_action(page, action: dict, target_url: str) -> bool:
    atype = action.get("type")
    if atype == "done":
        return True
    try:
        if atype == "click":
            text = action.get("text", "")
            last_err: Exception | None = None
            for i, candidate in enumerate(_click_candidates(text)):
                timeout = 1500 if i < 2 else 3000
                try:
                    await page.get_by_text(candidate, exact=False).first.click(
                        timeout=timeout
                    )
                    if i > 0:
                        print(f"  (fallback matched on '{candidate}')")
                    return False
                except Exception as e:
                    last_err = e
            if last_err:
                raise last_err
        elif atype == "fill":
            sel = action.get("selector", "")
            val = action.get("value", "")
            await page.locator(sel).fill(val, timeout=5000)
        elif atype == "navigate":
            url = action.get("url", "")
            if url.startswith("/"):
                url = target_url.rstrip("/") + url
            await page.goto(url)
    except Exception as e:
        print(f"  [{action.get('type', '?')} failed for '{action.get('text', '')}': {type(e).__name__}]")
    return False


# ---------------------------------------------------------------------------
# Sync runner (used by run_one CLI and any non-async caller)
# ---------------------------------------------------------------------------

def run_persona(
    persona: Persona,
    target_url: str,
    goal: str | None = None,
    max_steps: int = MAX_STEPS,
    headless: bool = False,
    verbose: bool = True,
) -> PersonaReport:
    from playwright.sync_api import sync_playwright

    goal = goal or persona_default_goal(persona)
    llm = get_llm_client(
        provider=getattr(persona, "llm_provider", None),
        model=getattr(persona, "llm_model", None),
    )
    effective_provider = (
        getattr(persona, "llm_provider", None)
        or os.environ.get("LLM_PROVIDER", "gemini")
    )
    effective_model = getattr(persona, "llm_model", None) or "(env default)"
    if verbose:
        print(f"\n=== {persona.name} ({persona.archetype}) starting at {target_url} ===")
        print(f"Provider: {effective_provider} | Model: {effective_model}")
        print(f"Goal: {goal}\n")

    started = time.time()
    observations: list[Observation] = []
    recent_actions: list[str] = []  # short-term memory, last N action summaries
    MEMORY_SIZE = 4
    completed = False

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()
        page.goto(target_url)
        page.wait_for_load_state("networkidle")

        for step in range(1, max_steps + 1):
            screenshot = page.screenshot(type="png")
            current_url = page.url
            if verbose:
                print(f"--- Step {step} | {current_url}")

            try:
                decision = _decide_next_action(
                    llm, persona, goal, screenshot,
                    recent_actions=recent_actions,
                )
            except Exception as e:
                if verbose:
                    print(f"  [LLM error: {e}]")
                break

            thought = decision.get("thought", "")
            friction = decision.get("friction")
            action = decision.get("action", {})

            if verbose:
                print(f"  💭 {thought}")
                if friction:
                    print(f"  ⚠️  friction: {friction}")
                print(f"  → action: {json.dumps(action)}")

            observations.append(
                Observation(
                    step=step,
                    page_url=current_url,
                    persona_thought=thought,
                    action_taken=action,
                    friction_noted=friction,
                )
            )

            # Update short-term memory
            recent_actions.append(_summarize_action_for_memory(action))
            if len(recent_actions) > MEMORY_SIZE:
                recent_actions = recent_actions[-MEMORY_SIZE:]

            done = _execute_sync_action(page, action, target_url)
            if done:
                if verbose:
                    print(f"  ✓ done: {action.get('reason')}")
                completed = "purchase" in (action.get("reason") or "").lower()
                break

            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
            time.sleep(0.4)

        if verbose:
            print(f"\n=== Generating final report ===")
        report_data = _build_final_report(llm, persona, observations, completed)
        browser.close()

    return PersonaReport(
        persona_id=persona.id,
        persona_name=persona.name,
        target_url=target_url,
        started_at=started,
        finished_at=time.time(),
        completed_purchase=report_data.get("completed_purchase", completed),
        final_assessment=report_data.get("final_assessment", ""),
        friction_points=report_data.get("friction_points", []),
        possible_bugs=report_data.get("possible_bugs", []),
        observations=observations,
    )


# ---------------------------------------------------------------------------
# Async runner — same logic, async Playwright. Used by full_loop in parallel.
# ---------------------------------------------------------------------------

async def run_persona_async(
    persona: Persona,
    target_url: str,
    goal: str | None = None,
    max_steps: int = MAX_STEPS,
    headless: bool = True,
    verbose: bool = False,
) -> PersonaReport:
    from playwright.async_api import async_playwright

    goal = goal or persona_default_goal(persona)
    llm = get_llm_client(
        provider=getattr(persona, "llm_provider", None),
        model=getattr(persona, "llm_model", None),
    )
    started = time.time()
    observations: list[Observation] = []
    recent_actions: list[str] = []
    MEMORY_SIZE = 4
    completed = False

    if verbose:
        effective_provider = (
            getattr(persona, "llm_provider", None)
            or os.environ.get("LLM_PROVIDER", "gemini")
        )
        effective_model = getattr(persona, "llm_model", None) or "(env default)"
        print(
            f"[{persona.id}] starting ({persona.archetype}) "
            f"headless={headless} provider={effective_provider} model={effective_model}"
        )

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=headless)
        context = await browser.new_context(viewport={"width": 1280, "height": 800})
        page = await context.new_page()
        await page.goto(target_url)
        try:
            await page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass

        for step in range(1, max_steps + 1):
            screenshot = await page.screenshot(type="png")
            current_url = page.url

            # LLM calls are sync (Gemini/OpenAI SDK) — run in a thread
            try:
                decision = await asyncio.to_thread(
                    _decide_next_action,
                    llm, persona, goal, screenshot, recent_actions,
                )
            except Exception as e:
                if verbose:
                    print(f"[{persona.id}] LLM error: {e}")
                break

            thought = decision.get("thought", "")
            friction = decision.get("friction")
            action = decision.get("action", {})

            if verbose:
                print(f"[{persona.id}] step {step} | {action.get('type', '?')}: {action.get('text') or action.get('reason') or ''}")

            observations.append(
                Observation(
                    step=step,
                    page_url=current_url,
                    persona_thought=thought,
                    action_taken=action,
                    friction_noted=friction,
                )
            )

            # Update short-term memory
            recent_actions.append(_summarize_action_for_memory(action))
            if len(recent_actions) > MEMORY_SIZE:
                recent_actions = recent_actions[-MEMORY_SIZE:]

            done = await _execute_async_action(page, action, target_url)
            if done:
                completed = "purchase" in (action.get("reason") or "").lower()
                break

            try:
                await page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
            await asyncio.sleep(0.4)

        report_data = await asyncio.to_thread(
            _build_final_report, llm, persona, observations, completed
        )
        await browser.close()

    if verbose:
        print(f"[{persona.id}] done — {len(observations)} steps, {len(report_data.get('possible_bugs', []))} bugs flagged")

    return PersonaReport(
        persona_id=persona.id,
        persona_name=persona.name,
        target_url=target_url,
        started_at=started,
        finished_at=time.time(),
        completed_purchase=report_data.get("completed_purchase", completed),
        final_assessment=report_data.get("final_assessment", ""),
        friction_points=report_data.get("friction_points", []),
        possible_bugs=report_data.get("possible_bugs", []),
        observations=observations,
    )


# ---------------------------------------------------------------------------
# Per-persona default goal
# ---------------------------------------------------------------------------

def persona_default_goal(persona: Persona) -> str:
    """Use the persona's own goal if defined, else the generic one."""
    goal = getattr(persona, "goal", None)
    return goal or DEFAULT_GOAL


# ---------------------------------------------------------------------------
# CLI (single persona, sync, headed by default)
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Run one persona against a target site.")
    parser.add_argument("--persona", default="maria", help="persona id from persona_profiles.py")
    parser.add_argument("--target", default="http://localhost:8000", help="target site URL")
    parser.add_argument("--headless", action="store_true", help="run headless")
    parser.add_argument("--max-steps", type=int, default=MAX_STEPS)
    args = parser.parse_args()

    persona = get_persona(args.persona)
    report = run_persona(
        persona=persona,
        target_url=args.target,
        max_steps=args.max_steps,
        headless=args.headless,
    )

    reports_dir = Path(__file__).parent / "reports"
    reports_dir.mkdir(exist_ok=True)
    out_path = reports_dir / f"{persona.id}_{int(report.started_at)}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(asdict(report), f, indent=2, ensure_ascii=False)

    print("\n" + "=" * 70)
    print(f"  REPORT — {report.persona_name}")
    print("=" * 70)
    print(f"  Completed purchase: {report.completed_purchase}")
    print(f"  Duration: {report.finished_at - report.started_at:.1f}s")
    print(f"  Steps: {len(report.observations)}")
    print()
    print(f"  Final assessment:")
    print(f"    {report.final_assessment}")
    print()
    if report.friction_points:
        print(f"  Friction points:")
        for fp in report.friction_points:
            print(f"    - {fp}")
        print()
    if report.possible_bugs:
        print(f"  🐛 Possible bugs:")
        for b in report.possible_bugs:
            print(f"    - {b}")
        print()
    print(f"  Full report: {out_path}")
    print("=" * 70)


if __name__ == "__main__":
    main()
