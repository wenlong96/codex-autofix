"""
Sandbox — isolated copy of the project for safely testing patches.

The orchestrator never modifies the live prototype directly. Instead:
  1. Create a sandbox (snapshot of current project state)
  2. Apply the proposed patch in the sandbox
  3. Run pytest in the sandbox
  4. If green, promote the patch to the live prototype (or open a PR)
  5. If red, throw it away and try again

We use shutil.copytree (not git worktree) because:
  - Captures uncommitted changes naturally (you'll have many during the hackathon)
  - No git dependency / no "did you commit?" gotchas
  - Identical behavior on Win/Mac/Linux
  - Project is small enough that copy is fast (<1s)

Sandboxes live in:
  Windows:  %TEMP%\\codex_sandboxes\\sb_<id>\\
  Mac/Lin:  /tmp/codex_sandboxes/sb_<id>/

They're cleaned up automatically when the Sandbox context manager exits, or
manually via .cleanup(). Stale sandboxes can be wiped with `clean_all_sandboxes()`.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

# Directories / files we never need in a sandbox
_IGNORE_DIRS = {
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    ".pytest_cache",
    "node_modules",
    "reports",
    "codex_sandboxes",  # safety: never recursively copy our own sandbox dir
}

_IGNORE_SUFFIXES = (".pyc", ".db", ".log")


def _ignore(dir_path: str, names: list[str]) -> list[str]:
    ignored = []
    for n in names:
        if n in _IGNORE_DIRS:
            ignored.append(n)
        elif n.endswith(_IGNORE_SUFFIXES):
            ignored.append(n)
    return ignored


@dataclass
class TestResult:
    passed: bool
    return_code: int
    stdout: str
    stderr: str

    def summary(self) -> str:
        """One-line summary for logging."""
        if self.passed:
            return "✓ All tests passed"
        return f"✗ Tests failed (exit {self.return_code})"


class Sandbox:
    """A snapshot of the project where patches can be safely tested."""

    def __init__(self, path: Path, source_root: Path):
        self.path = path
        self.source_root = source_root

    # ---- creation / cleanup ------------------------------------------------

    @classmethod
    def create(
        cls,
        source_root: Path | None = None,
        name: str | None = None,
    ) -> "Sandbox":
        """Snapshot the current project into a new sandbox."""
        if source_root is None:
            # Default: project root (parent of orchestrator/)
            source_root = Path(__file__).resolve().parent.parent
        source_root = source_root.resolve()

        if not source_root.exists():
            raise FileNotFoundError(f"Source root does not exist: {source_root}")

        sandbox_root = Path(tempfile.gettempdir()) / "codex_sandboxes"
        sandbox_root.mkdir(parents=True, exist_ok=True)

        name = name or f"sb_{uuid.uuid4().hex[:8]}"
        path = sandbox_root / name

        if path.exists():
            shutil.rmtree(path)

        shutil.copytree(source_root, path, ignore=_ignore)

        return cls(path=path, source_root=source_root)

    def cleanup(self) -> None:
        """Delete this sandbox."""
        if self.path.exists():
            shutil.rmtree(self.path, ignore_errors=True)

    def __enter__(self) -> "Sandbox":
        return self

    def __exit__(self, *exc) -> None:
        self.cleanup()

    # ---- file ops ----------------------------------------------------------

    def read_file(self, rel_path: str | Path) -> str:
        """Read a file inside the sandbox."""
        target = self.path / rel_path
        if not target.exists():
            raise FileNotFoundError(f"Not in sandbox: {rel_path}")
        return target.read_text(encoding="utf-8")

    def write_file(self, rel_path: str | Path, content: str) -> None:
        """Write a file inside the sandbox (creating parents as needed)."""
        target = self.path / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def list_files(self, subdir: str = "", pattern: str = "*") -> list[str]:
        """List files in the sandbox (paths relative to sandbox root)."""
        base = self.path / subdir if subdir else self.path
        return [
            str(p.relative_to(self.path))
            for p in base.rglob(pattern)
            if p.is_file()
        ]

    # ---- promote to live ---------------------------------------------------

    def promote_file(self, rel_path: str | Path) -> None:
        """Copy a file from the sandbox back to the live source tree."""
        src = self.path / rel_path
        dst = self.source_root / rel_path
        if not src.exists():
            raise FileNotFoundError(f"Not in sandbox: {rel_path}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    # ---- tests -------------------------------------------------------------

    def run_tests(
        self,
        test_path: str = "prototype/tests/",
        timeout: int = 120,
        extra_args: list[str] | None = None,
    ) -> TestResult:
        """Run pytest inside the sandbox."""
        cmd = [sys.executable, "-m", "pytest", test_path, "-v", "--tb=short"]
        if extra_args:
            cmd.extend(extra_args)

        # pytest needs to be run from prototype/ since the tests import
        # from `main` and `seed` directly (not from a package).
        run_cwd = self.path / "prototype"

        try:
            proc = subprocess.run(
                cmd,
                cwd=run_cwd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return TestResult(
                passed=False,
                return_code=-1,
                stdout="",
                stderr=f"pytest timed out after {timeout}s",
            )

        return TestResult(
            passed=proc.returncode == 0,
            return_code=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
        )


def clean_all_sandboxes() -> int:
    """Delete every sandbox under the system temp dir. Returns count removed."""
    sandbox_root = Path(tempfile.gettempdir()) / "codex_sandboxes"
    if not sandbox_root.exists():
        return 0
    count = sum(1 for _ in sandbox_root.iterdir())
    shutil.rmtree(sandbox_root)
    return count
