"""
LLM-autonomous backend inspector agents.

These agents do not drive a browser. They inspect the API surface, ask an LLM to
plan probes from an agent-specific mission, execute those probes, then ask the
LLM to judge the observed responses and emit the same PersonaReport shape as the
browser personas.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from personas.llm_client import get_llm_client
from personas.run_one import PersonaReport


@dataclass
class ApiResponse:
    status: int
    body: Any
    text: str


@dataclass
class Probe:
    method: str
    path: str
    body: dict[str, Any] | None
    why: str


def _url(target_url: str, path: str) -> str:
    return f"{target_url.rstrip('/')}/{path.lstrip('/')}"


def _request_json(
    target_url: str,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    timeout: float = 8.0,
) -> ApiResponse:
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(
        _url(target_url, path),
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", errors="replace")
            return ApiResponse(resp.status, _parse_body(text), text)
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", errors="replace")
        return ApiResponse(e.code, _parse_body(text), text)


def _parse_body(text: str) -> Any:
    try:
        return json.loads(text)
    except Exception:
        return None


def _create_team(target_url: str, user_id: str, product_id: int = 1) -> str | None:
    resp = _request_json(
        target_url,
        "POST",
        "/api/teams",
        {"product_id": product_id, "user_id": user_id},
    )
    if resp.status != 200 or not isinstance(resp.body, dict):
        return None
    team_id = resp.body.get("team_id")
    return str(team_id) if team_id else None


def _get_openapi(target_url: str) -> dict[str, Any]:
    resp = _request_json(target_url, "GET", "/openapi.json")
    if resp.status != 200 or not isinstance(resp.body, dict):
        raise RuntimeError(f"Could not fetch /openapi.json: HTTP {resp.status}")
    return resp.body


def _planner_system(agent_name: str, mission: str) -> str:
    return f"""You are {agent_name}, an autonomous backend QA agent.

Mission:
{mission}

Read the API surface and choose concrete probes that will reveal likely bugs.
You are not writing unit tests. You are deciding what API calls to make.

Return ONLY JSON:
{{
  "setup_notes": "short explanation of your strategy",
  "probes": [
    {{
      "method": "POST",
      "path": "/api/teams",
      "body": {{"product_id": 1, "user_id": "example"}},
      "why": "why this probe matters"
    }}
  ]
}}

Rules:
- Include setup calls required by later probes.
- Use concrete JSON bodies.
- Prefer 3-6 probes total.
- Do not invent endpoints that are not in the API surface."""


def _judge_system(agent_name: str, mission: str) -> str:
    return f"""You are {agent_name}, an autonomous backend QA agent.

Mission:
{mission}

You planned and executed API probes. Decide which observed responses are real
bugs. Be specific enough that a verifier can inspect source code and confirm the
bug.

Return ONLY JSON:
{{
  "final_assessment": "2-3 sentences summarizing what you probed and found",
  "possible_bugs": [
    "specific bug report with endpoint, input, observed response, and expected behavior"
  ]
}}

Only report actual contract, validation, authorization, or business-rule bugs.
Do not report a setup failure as a product bug."""


def _plan_probes(
    target_url: str,
    agent_name: str,
    mission: str,
    llm_provider: str | None = None,
    llm_model: str | None = None,
) -> tuple[str, list[Probe]]:
    surface = _get_openapi(target_url)
    llm = get_llm_client(provider=llm_provider, model=llm_model)
    plan = llm.complete_json(
        system=_planner_system(agent_name, mission),
        user=(
            "API surface from /openapi.json:\n"
            f"{json.dumps(surface, indent=2)[:12000]}"
        ),
        temperature=0.35,
        max_tokens=1800,
    )
    probes: list[Probe] = []
    for raw in plan.get("probes", []):
        if not isinstance(raw, dict):
            continue
        method = str(raw.get("method", "GET")).upper()
        path = str(raw.get("path", "")).strip()
        if not path.startswith("/"):
            continue
        body = raw.get("body")
        if body is not None and not isinstance(body, dict):
            body = None
        probes.append(
            Probe(
                method=method,
                path=path,
                body=body,
                why=str(raw.get("why", "")).strip(),
            )
        )
    return str(plan.get("setup_notes", "")).strip(), probes


def _execute_probes(
    target_url: str,
    probes: list[Probe],
) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    created_team_id: str | None = None

    for probe in probes:
        path = probe.path
        body = dict(probe.body or {})

        # Let the LLM use a readable placeholder without knowing the runtime id.
        if "{team_id}" in path and created_team_id:
            path = path.replace("{team_id}", created_team_id)

        resp = _request_json(target_url, probe.method, path, body or None)
        if path == "/api/teams" and resp.status == 200 and isinstance(resp.body, dict):
            team_id = resp.body.get("team_id")
            if team_id:
                created_team_id = str(team_id)

        observations.append(
            {
                "method": probe.method,
                "path": path,
                "body": body or None,
                "why": probe.why,
                "status": resp.status,
                "response": resp.body if resp.body is not None else resp.text[:500],
            }
        )
    return observations


def _judge_observations(
    agent_name: str,
    mission: str,
    setup_notes: str,
    observations: list[dict[str, Any]],
    llm_provider: str | None = None,
    llm_model: str | None = None,
) -> dict[str, Any]:
    llm = get_llm_client(provider=llm_provider, model=llm_model)
    return llm.complete_json(
        system=_judge_system(agent_name, mission),
        user=(
            f"Planner setup notes:\n{setup_notes}\n\n"
            "Observed probe results:\n"
            f"{json.dumps(observations, indent=2)}"
        ),
        temperature=0.25,
        max_tokens=1600,
    )


def _deterministic_report(
    target_url: str,
    persona_id: str,
    persona_name: str,
    possible_bugs: list[str],
    final_assessment: str,
    started: float,
) -> PersonaReport:
    return PersonaReport(
        persona_id=persona_id,
        persona_name=persona_name,
        target_url=target_url,
        started_at=started,
        finished_at=time.time(),
        completed_purchase=False,
        final_assessment=final_assessment,
        friction_points=[],
        possible_bugs=possible_bugs,
        observations=[],
    )


def _run_llm_backend_agent(
    target_url: str,
    persona_id: str,
    persona_name: str,
    mission: str,
    llm_provider: str | None = None,
    llm_model: str | None = None,
) -> PersonaReport:
    started = time.time()
    setup_notes, probes = _plan_probes(
        target_url,
        persona_name,
        mission,
        llm_provider=llm_provider,
        llm_model=llm_model,
    )
    observations = _execute_probes(target_url, probes)
    judged = _judge_observations(
        persona_name,
        mission,
        setup_notes,
        observations,
        llm_provider=llm_provider,
        llm_model=llm_model,
    )
    possible_bugs = judged.get("possible_bugs", [])
    if not isinstance(possible_bugs, list):
        possible_bugs = []
    possible_bugs = [str(b) for b in possible_bugs if str(b).strip()]
    final_assessment = str(judged.get("final_assessment", "")).strip()
    if not final_assessment:
        final_assessment = (
            f"Planned {len(probes)} probe(s) and executed {len(observations)} "
            "API request(s)."
        )
    return _deterministic_report(
        target_url=target_url,
        persona_id=persona_id,
        persona_name=persona_name,
        possible_bugs=possible_bugs,
        final_assessment=final_assessment,
        started=started,
    )


def run_api_fuzzer_inspector(
    target_url: str,
    planner: str = "llm",
    llm_provider: str | None = None,
    llm_model: str | None = None,
) -> PersonaReport:
    """
    BE-1: non-positive join quantities must be rejected with 400.
    """
    started = time.time()
    mission = (
        "Find API contract and input-validation bugs in the team-purchase "
        "checkout flow. Focus on boundary quantities, invalid request bodies, "
        "and values that could create impossible financial totals."
    )
    if planner == "llm":
        return _run_llm_backend_agent(
            target_url,
            "api_fuzzer",
            "API Fuzzer / Contract Agent",
            mission,
            llm_provider=llm_provider,
            llm_model=llm_model,
        )

    possible_bugs: list[str] = []
    observations: list[str] = []

    team_id = _create_team(target_url, user_id="fuzz_creator")
    if not team_id:
        possible_bugs.append(
            "API Fuzzer could not create a team with POST /api/teams, so it "
            "could not probe join quantity validation."
        )
    else:
        for qty in (-1, 0):
            resp = _request_json(
                target_url,
                "POST",
                f"/api/teams/{team_id}/join",
                {"user_id": f"fuzz_joiner_{qty}", "quantity": qty},
            )
            observations.append(
                f"POST /api/teams/{team_id}/join quantity={qty} -> HTTP {resp.status}"
            )
            if resp.status == 200:
                possible_bugs.append(
                    "POST /api/teams/{team_id}/join accepted "
                    f"quantity={qty} with HTTP 200; expected 400. "
                    "join_team() should reject non-positive quantities before "
                    "they are stored because they can flow into checkout totals."
                )

    return PersonaReport(
        persona_id="api_fuzzer",
        persona_name="API Fuzzer / Contract Agent",
        target_url=target_url,
        started_at=started,
        finished_at=time.time(),
        completed_purchase=False,
        final_assessment=(
            "Probed join-team quantity boundaries. "
            + ("; ".join(observations) if observations else "No probe completed.")
        ),
        friction_points=[],
        possible_bugs=possible_bugs,
        observations=[],
    )


def run_security_auth_inspector(
    target_url: str,
    planner: str = "llm",
    llm_provider: str | None = None,
    llm_model: str | None = None,
) -> PersonaReport:
    """
    BE-2: a team creator must not be allowed to join their own team.
    """
    started = time.time()
    mission = (
        "Find authorization and state-transition bugs in the team-purchase API. "
        "Focus on whether one user can abuse another user's team, replay their "
        "own identity, or unlock team-only behavior without a legitimate second "
        "buyer."
    )
    if planner == "llm":
        return _run_llm_backend_agent(
            target_url,
            "security_auth",
            "Security / Auth Agent",
            mission,
            llm_provider=llm_provider,
            llm_model=llm_model,
        )

    possible_bugs: list[str] = []

    creator_id = "alice_security_probe"
    team_id = _create_team(target_url, user_id=creator_id)
    if not team_id:
        final = (
            "Security/Auth could not create a team with POST /api/teams, so it "
            "could not probe creator self-join authorization."
        )
        possible_bugs.append(final)
    else:
        resp = _request_json(
            target_url,
            "POST",
            f"/api/teams/{team_id}/join",
            {"user_id": creator_id, "quantity": 1},
        )
        final = (
            f"POST /api/teams/{team_id}/join as creator {creator_id} "
            f"returned HTTP {resp.status}."
        )
        if resp.status == 200:
            possible_bugs.append(
                "POST /api/teams/{team_id}/join allowed the team creator to "
                "join their own team with HTTP 200; expected 400. This lets "
                "one user reach member_count=2 and unlock the team discount "
                "without a second real buyer."
            )

    return PersonaReport(
        persona_id="security_auth",
        persona_name="Security / Auth Agent",
        target_url=target_url,
        started_at=started,
        finished_at=time.time(),
        completed_purchase=False,
        final_assessment=final,
        friction_points=[],
        possible_bugs=possible_bugs,
        observations=[],
    )


def run_backend_inspectors(
    target_url: str,
    planner: str = "llm",
    llm_provider: str | None = None,
    llm_model: str | None = None,
) -> dict[str, PersonaReport]:
    reports = {
        "api_fuzzer": run_api_fuzzer_inspector(
            target_url,
            planner=planner,
            llm_provider=llm_provider,
            llm_model=llm_model,
        ),
        "security_auth": run_security_auth_inspector(
            target_url,
            planner=planner,
            llm_provider=llm_provider,
            llm_model=llm_model,
        ),
    }
    return reports
