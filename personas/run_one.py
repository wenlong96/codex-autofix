"""
Run one persona end-to-end against the prototype.

Usage:
    python run_one.py --persona maria --target http://localhost:8000

Set LLM_PROVIDER=gemini (default) or openai in .env.

What it does:
    1. Launches a headed Chromium browser via Playwright.
    2. The persona navigates the site via screenshot -> LLM reasoning -> action.
    3. Each loop step: screenshot the page, ask the LLM "as Maria, what's your
       next action?" with structured output (click_text | fill | back | done).
    4. Records observations (friction, surprising prices, things that look
       wrong).
    5. At the end, asks the LLM to write a structured report.

Output:
    - Console: live narration of what the persona is doing
    - reports/<persona_id>_<timestamp>.json: full structured report
"""

from __future__ import annotations

import argparse
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
    // for "click": which element. prefer visible text.
    "text": "exact visible text of the button/link to click",
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

{ACTION_SCHEMA}"""


def build_report_system_prompt(persona: Persona) -> str:
    return f"""{persona.to_prompt_block()}

You just finished a shopping session. Write an honest debrief.

Return a JSON object:
{{
  "completed_purchase": true/false,
  "final_assessment": "2-3 sentences. Would you actually buy from this site? What stood out — good or bad?",
  "friction_points": ["specific UX issues you hit, one per item"],
  "possible_bugs": ["anything that looked wrong/broken/sketchy. Be specific. e.g. 'The savings number was 26.97 when only I was in the team — that math doesn't add up for 1 person.'"]
}}

Return ONLY the JSON."""


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

DEFAULT_GOAL = (
    "Browse the site. Find a product you might buy. If there's a team-purchase "
    "discount, decide whether it's worth it for you. Try to complete a purchase "
    "if it makes sense. Be your honest self — if something feels off, note it."
)

MAX_STEPS = 20


def run_persona(
    persona: Persona,
    target_url: str,
    goal: str = DEFAULT_GOAL,
    max_steps: int = MAX_STEPS,
    headless: bool = False,
) -> PersonaReport:
    from playwright.sync_api import sync_playwright

    llm = get_llm_client()
    print(f"\n=== {persona.name} ({persona.archetype}) starting at {target_url} ===\n")
    print(f"Provider: {os.environ.get('LLM_PROVIDER', 'gemini')}")
    print(f"Goal: {goal}\n")

    started = time.time()
    observations: list[Observation] = []
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

            print(f"--- Step {step} | {current_url}")

            try:
                decision = llm.complete_json(
                    system=build_action_system_prompt(persona, goal),
                    user="What's your next action?",
                    image_bytes=screenshot,
                    image_mime="image/png",
                    temperature=0.6,
                )
            except Exception as e:
                print(f"  [LLM error: {e}]")
                break

            thought = decision.get("thought", "")
            friction = decision.get("friction")
            action = decision.get("action", {})

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

            # Execute action
            atype = action.get("type")
            try:
                if atype == "done":
                    print(f"  ✓ done: {action.get('reason')}")
                    completed = "purchase" in (action.get("reason") or "").lower()
                    break
                if atype == "click":
                    text = action.get("text", "")
                    # Try multiple strategies
                    locator = page.get_by_text(text, exact=False).first
                    locator.click(timeout=5000)
                elif atype == "fill":
                    sel = action.get("selector", "")
                    val = action.get("value", "")
                    page.locator(sel).fill(val, timeout=5000)
                elif atype == "navigate":
                    url = action.get("url", "")
                    if url.startswith("/"):
                        url = target_url.rstrip("/") + url
                    page.goto(url)
                else:
                    print(f"  ⚠️  Unknown action type: {atype}")
                    break
            except Exception as e:
                print(f"  [Action failed: {e}]")
                # Don't break — let the persona see the failed state next loop
                pass

            page.wait_for_load_state("networkidle", timeout=10000)
            time.sleep(0.5)  # small pause so headed browser is watchable

        # --- Final report ---
        print(f"\n=== Generating final report ===")
        try:
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
            report_data = llm.complete_json(
                system=build_report_system_prompt(persona),
                user=f"Here's everything you did and noticed:\n\n{history_summary}\n\nNow write your debrief.",
                temperature=0.4,
                max_tokens=1500,
            )
        except Exception as e:
            print(f"[Report generation failed: {e}]")
            report_data = {
                "completed_purchase": completed,
                "final_assessment": "Report generation failed.",
                "friction_points": [],
                "possible_bugs": [],
            }

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
# CLI
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

    # Save report
    reports_dir = Path(__file__).parent / "reports"
    reports_dir.mkdir(exist_ok=True)
    out_path = reports_dir / f"{persona.id}_{int(report.started_at)}.json"

    report_dict = asdict(report)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report_dict, f, indent=2, ensure_ascii=False)

    # Pretty summary
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
