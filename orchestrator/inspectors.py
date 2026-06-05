"""
Backend inspector agents.

These agents do not drive a browser. They probe the API directly, then emit the
same PersonaReport shape as the browser personas so the existing aggregate /
verify / heal pipeline can consume them unchanged.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from personas.run_one import PersonaReport


@dataclass
class ApiResponse:
    status: int
    body: Any
    text: str


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


def run_api_fuzzer_inspector(target_url: str) -> PersonaReport:
    """
    BE-1: non-positive join quantities must be rejected with 400.
    """
    started = time.time()
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


def run_security_auth_inspector(target_url: str) -> PersonaReport:
    """
    BE-2: a team creator must not be allowed to join their own team.
    """
    started = time.time()
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


def run_backend_inspectors(target_url: str) -> dict[str, PersonaReport]:
    reports = {
        "api_fuzzer": run_api_fuzzer_inspector(target_url),
        "security_auth": run_security_auth_inspector(target_url),
    }
    return reports
