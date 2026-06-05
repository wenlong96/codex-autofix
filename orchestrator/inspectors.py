"""
LLM-autonomous backend inspector agents.

These agents do not drive a browser. They inspect the API surface, ask an LLM to
plan probes from an agent-specific mission, execute those probes, then ask the
LLM to judge the observed responses and emit the same PersonaReport shape as the
browser personas.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from personas.llm_client import get_llm_client
from personas.run_one import Observation, PersonaReport


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
    persona_id: str | None = None,
    verbose: bool = True,
) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    created_team_id: str | None = None

    for step, probe in enumerate(probes, 1):
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
                "step": step,
                "method": probe.method,
                "path": path,
                "body": body or None,
                "why": probe.why,
                "status": resp.status,
                "response": resp.body if resp.body is not None else resp.text[:500],
            }
        )
        if verbose and persona_id:
            print(f"[{persona_id}] step {step} | {probe.method} {path} -> HTTP {resp.status}")
    return observations


def _api_observations_to_persona_observations(
    target_url: str,
    api_observations: list[dict[str, Any]],
) -> list[Observation]:
    out: list[Observation] = []
    for i, obs in enumerate(api_observations, 1):
        method = str(obs.get("method", "GET")).upper()
        path = str(obs.get("path", "/"))
        status = obs.get("status")
        response = obs.get("response")
        out.append(
            Observation(
                step=int(obs.get("step") or i),
                page_url=_url(target_url, path),
                persona_thought=str(obs.get("why") or f"Probe {method} {path}."),
                action_taken={
                    "type": "api_probe",
                    "method": method,
                    "path": path,
                    "body": obs.get("body"),
                    "status": status,
                    "response": response,
                },
                friction_noted=f"HTTP {status}" if isinstance(status, int) and status >= 400 else None,
            )
        )
    return out


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
    observations: list[Observation] | None = None,
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
        observations=observations or [],
    )


def _run_llm_backend_agent(
    target_url: str,
    persona_id: str,
    persona_name: str,
    mission: str,
    llm_provider: str | None = None,
    llm_model: str | None = None,
    verbose: bool = True,
) -> PersonaReport:
    started = time.time()
    if verbose:
        provider, model = _effective_llm_label(llm_provider, llm_model)
        print(
            f"[{persona_id}] starting (backend_inspector) "
            f"planner=llm provider={provider} model={model}"
        )
    setup_notes, probes = _plan_probes(
        target_url,
        persona_name,
        mission,
        llm_provider=llm_provider,
        llm_model=llm_model,
    )
    if verbose:
        print(f"[{persona_id}] planned {len(probes)} API probe(s)")
        if setup_notes:
            print(f"[{persona_id}] plan: {setup_notes}")
    api_observations = _execute_probes(
        target_url,
        probes,
        persona_id=persona_id,
        verbose=verbose,
    )
    judged = _judge_observations(
        persona_name,
        mission,
        setup_notes,
        api_observations,
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
            f"Planned {len(probes)} probe(s) and executed {len(api_observations)} "
            "API request(s)."
        )
    observations = _api_observations_to_persona_observations(target_url, api_observations)
    if verbose:
        print(f"[{persona_id}] done - {len(observations)} steps, {len(possible_bugs)} bugs flagged")
    return _deterministic_report(
        target_url=target_url,
        persona_id=persona_id,
        persona_name=persona_name,
        possible_bugs=possible_bugs,
        final_assessment=final_assessment,
        started=started,
        observations=observations,
    )


def run_api_fuzzer_inspector(
    target_url: str,
    planner: str = "llm",
    llm_provider: str | None = None,
    llm_model: str | None = None,
    verbose: bool = True,
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
            verbose=verbose,
        )

    possible_bugs: list[str] = []
    api_observations: list[dict[str, Any]] = []

    if verbose:
        print(f"[api_fuzzer] starting (backend_inspector) planner=deterministic")

    setup_body = {"product_id": 1, "user_id": "fuzz_creator"}
    setup_resp = _request_json(target_url, "POST", "/api/teams", setup_body)
    team_id = None
    if setup_resp.status == 200 and isinstance(setup_resp.body, dict):
        raw_team_id = setup_resp.body.get("team_id")
        team_id = str(raw_team_id) if raw_team_id else None
    api_observations.append(
        {
            "step": 1,
            "method": "POST",
            "path": "/api/teams",
            "body": setup_body,
            "why": "Create a valid team so quantity-boundary join probes have a real target.",
            "status": setup_resp.status,
            "response": setup_resp.body if setup_resp.body is not None else setup_resp.text[:500],
        }
    )
    if verbose:
        print(f"[api_fuzzer] step 1 | POST /api/teams -> HTTP {setup_resp.status}")
    if not team_id:
        possible_bugs.append(
            "API Fuzzer could not create a team with POST /api/teams, so it "
            "could not probe join quantity validation."
        )
    else:
        for step, qty in enumerate((-1, 0), 2):
            path = f"/api/teams/{team_id}/join"
            body = {"user_id": f"fuzz_joiner_{qty}", "quantity": qty}
            resp = _request_json(
                target_url,
                "POST",
                path,
                body,
            )
            api_observations.append(
                {
                    "step": step,
                    "method": "POST",
                    "path": path,
                    "body": body,
                    "why": f"Probe whether join_team rejects non-positive quantity={qty}.",
                    "status": resp.status,
                    "response": resp.body if resp.body is not None else resp.text[:500],
                }
            )
            if verbose:
                print(f"[api_fuzzer] step {step} | POST {path} -> HTTP {resp.status}")
            if resp.status == 200:
                possible_bugs.append(
                    "POST /api/teams/{team_id}/join accepted "
                    f"quantity={qty} with HTTP 200; expected 400. "
                    "join_team() should reject non-positive quantities before "
                    "they are stored because they can flow into checkout totals."
                )

    observations = _api_observations_to_persona_observations(target_url, api_observations)
    if verbose:
        print(f"[api_fuzzer] done - {len(observations)} steps, {len(possible_bugs)} bugs flagged")
    return PersonaReport(
        persona_id="api_fuzzer",
        persona_name="API Fuzzer / Contract Agent",
        target_url=target_url,
        started_at=started,
        finished_at=time.time(),
        completed_purchase=False,
        final_assessment=(
            "Probed join-team quantity boundaries. "
            + (
                "; ".join(
                    f"{o['method']} {o['path']} -> HTTP {o['status']}"
                    for o in api_observations
                )
                if api_observations
                else "No probe completed."
            )
        ),
        friction_points=[],
        possible_bugs=possible_bugs,
        observations=observations,
    )


def run_security_auth_inspector(
    target_url: str,
    planner: str = "llm",
    llm_provider: str | None = None,
    llm_model: str | None = None,
    verbose: bool = True,
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
            verbose=verbose,
        )

    possible_bugs: list[str] = []
    api_observations: list[dict[str, Any]] = []

    if verbose:
        print(f"[security_auth] starting (backend_inspector) planner=deterministic")

    creator_id = "alice_security_probe"
    setup_body = {"product_id": 1, "user_id": creator_id}
    setup_resp = _request_json(target_url, "POST", "/api/teams", setup_body)
    team_id = None
    if setup_resp.status == 200 and isinstance(setup_resp.body, dict):
        raw_team_id = setup_resp.body.get("team_id")
        team_id = str(raw_team_id) if raw_team_id else None
    api_observations.append(
        {
            "step": 1,
            "method": "POST",
            "path": "/api/teams",
            "body": setup_body,
            "why": "Create a team as the target user before probing creator self-join authorization.",
            "status": setup_resp.status,
            "response": setup_resp.body if setup_resp.body is not None else setup_resp.text[:500],
        }
    )
    if verbose:
        print(f"[security_auth] step 1 | POST /api/teams -> HTTP {setup_resp.status}")
    if not team_id:
        final = (
            "Security/Auth could not create a team with POST /api/teams, so it "
            "could not probe creator self-join authorization."
        )
        possible_bugs.append(final)
    else:
        path = f"/api/teams/{team_id}/join"
        body = {"user_id": creator_id, "quantity": 1}
        resp = _request_json(
            target_url,
            "POST",
            path,
            body,
        )
        api_observations.append(
            {
                "step": 2,
                "method": "POST",
                "path": path,
                "body": body,
                "why": "Probe whether a team creator can reuse their own identity to join the team.",
                "status": resp.status,
                "response": resp.body if resp.body is not None else resp.text[:500],
            }
        )
        if verbose:
            print(f"[security_auth] step 2 | POST {path} -> HTTP {resp.status}")
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

    observations = _api_observations_to_persona_observations(target_url, api_observations)
    if verbose:
        print(f"[security_auth] done - {len(observations)} steps, {len(possible_bugs)} bugs flagged")
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
        observations=observations,
    )


def run_backend_inspectors(
    target_url: str,
    planner: str = "llm",
    llm_provider: str | None = None,
    llm_model: str | None = None,
    verbose: bool = True,
) -> dict[str, PersonaReport]:
    reports = {
        "api_fuzzer": run_api_fuzzer_inspector(
            target_url,
            planner=planner,
            llm_provider=llm_provider,
            llm_model=llm_model,
            verbose=verbose,
        ),
        "security_auth": run_security_auth_inspector(
            target_url,
            planner=planner,
            llm_provider=llm_provider,
            llm_model=llm_model,
            verbose=verbose,
        ),
    }
    return reports
