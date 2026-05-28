"""
Tests for the Sandbox.

These verify:
  - A sandbox is created with the project copied in
  - Files written to the sandbox don't affect the live source
  - pytest can be invoked inside the sandbox and reports correctly
  - Promotion copies files back to the live source
  - Cleanup removes the sandbox directory

Run from project root:
    python -m pytest orchestrator/tests/ -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make orchestrator importable when running pytest from the project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from orchestrator.sandbox import Sandbox, clean_all_sandboxes  # noqa: E402


def test_sandbox_copies_project_files():
    """A new sandbox should have the prototype directory."""
    with Sandbox.create(source_root=PROJECT_ROOT) as sb:
        assert (sb.path / "prototype" / "main.py").exists()
        assert (sb.path / "prototype" / "static" / "index.html").exists()
        assert (sb.path / "prototype" / "tests" / "test_regressions.py").exists()


def test_sandbox_ignores_venv_and_caches():
    """The sandbox should not contain .venv, __pycache__, .git, etc."""
    with Sandbox.create(source_root=PROJECT_ROOT) as sb:
        assert not (sb.path / ".venv").exists()
        assert not (sb.path / ".git").exists()
        for p in sb.path.rglob("__pycache__"):
            pytest.fail(f"__pycache__ should not exist in sandbox: {p}")


def test_sandbox_modifications_do_not_leak():
    """Writing in the sandbox must not affect the live source."""
    live_main = PROJECT_ROOT / "prototype" / "main.py"
    original_content = live_main.read_text(encoding="utf-8")

    with Sandbox.create(source_root=PROJECT_ROOT) as sb:
        sb.write_file("prototype/main.py", "# CORRUPTED\n")
        assert sb.read_file("prototype/main.py") == "# CORRUPTED\n"

    # Live file must be unchanged
    assert live_main.read_text(encoding="utf-8") == original_content


def test_run_tests_in_sandbox_failing_bugs():
    """Running tests on the un-patched prototype should show real test failures."""
    with Sandbox.create(source_root=PROJECT_ROOT) as sb:
        result = sb.run_tests("tests/")
        # With bugs present, tests fail
        assert result.passed is False
        # ...but specifically a regression test, not crash/import errors
        combined = (result.stdout + result.stderr).lower()
        assert "failed" in combined
        assert "test_" in combined


def test_run_tests_in_sandbox_with_patched_savings():
    """
    Apply a known correct fix for the team-savings calculation in the sandbox,
    then verify that test now passes. (Other failing tests should still fail —
    we only fixed one.)
    """
    with Sandbox.create(source_root=PROJECT_ROOT) as sb:
        main_py = sb.read_file("prototype/main.py")

        # Replace the hardcoded `expected_member_count = 2` with len(members)
        patched = main_py.replace(
            "        expected_member_count = 2\n"
            "        total_savings = product[\"price\"] * TEAM_DISCOUNT * expected_member_count",
            "        total_savings = product[\"price\"] * TEAM_DISCOUNT * len(members)",
        )
        assert patched != main_py, "Patch did not apply — string not found"
        sb.write_file("prototype/main.py", patched)

        result = sb.run_tests("tests/test_regressions.py::test_team_savings_reflects_actual_member_count")
        assert result.passed is True, (
            f"Expected the team-savings test to pass after fix.\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )


def test_promote_file_writes_back_to_source(tmp_path):
    """
    Use a temporary fake project to verify promote_file works without
    touching the real prototype/.
    """
    fake_root = tmp_path / "fake_project"
    fake_root.mkdir()
    (fake_root / "prototype").mkdir()
    (fake_root / "prototype" / "main.py").write_text("ORIGINAL", encoding="utf-8")

    with Sandbox.create(source_root=fake_root) as sb:
        sb.write_file("prototype/main.py", "PATCHED")
        sb.promote_file("prototype/main.py")

    # After cleanup, the live source should reflect the patch
    assert (fake_root / "prototype" / "main.py").read_text(encoding="utf-8") == "PATCHED"


def test_cleanup_removes_sandbox():
    sb = Sandbox.create(source_root=PROJECT_ROOT)
    path = sb.path
    assert path.exists()
    sb.cleanup()
    assert not path.exists()


def test_context_manager_auto_cleanup():
    with Sandbox.create(source_root=PROJECT_ROOT) as sb:
        path = sb.path
        assert path.exists()
    assert not path.exists()


def test_clean_all_sandboxes_removes_stragglers():
    sb1 = Sandbox.create(source_root=PROJECT_ROOT)
    sb2 = Sandbox.create(source_root=PROJECT_ROOT)
    assert sb1.path.exists() and sb2.path.exists()

    removed = clean_all_sandboxes()
    assert removed >= 2
    assert not sb1.path.exists()
    assert not sb2.path.exists()
