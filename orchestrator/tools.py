"""
Tools exposed to the Codex agent (Responses API format).

Design choices:
  - write_file is full-file rewrite (not diff). Codex returns the entire new
    file content. Bulletproof against whitespace issues. We compute a diff
    afterwards for visualization.
  - All tools operate ON THE SANDBOX, never on the live source. Promotion to
    live happens only after tests pass, outside the agent loop.
  - Each tool returns a small dict that becomes the function_call_output.
    Keep return payloads compact — token budget matters.

Tool schemas use OpenAI's Responses API format (flat, no nested `function` key).
"""

from __future__ import annotations

import difflib
import json
from dataclasses import dataclass

from .sandbox import Sandbox, TestResult


# ---------------------------------------------------------------------------
# Tool schemas (sent to Codex via Responses API)
# ---------------------------------------------------------------------------

TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "name": "read_file",
        "description": (
            "Read a file from the sandbox. Use this to examine source code, "
            "tests, or any other file before proposing a fix."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Path relative to the project root, e.g. "
                        "'prototype/main.py' or "
                        "'prototype/tests/test_planted_bugs.py'."
                    ),
                }
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "list_files",
        "description": (
            "List files in a directory inside the sandbox. Useful to "
            "discover what code exists before reading it."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "subdir": {
                    "type": "string",
                    "description": (
                        "Directory relative to project root, e.g. "
                        "'prototype' or 'prototype/static'. Empty string "
                        "lists from the project root."
                    ),
                },
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern, e.g. '*.py' or '*'.",
                },
            },
            "required": ["subdir", "pattern"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "write_file",
        "description": (
            "Write the complete new contents of a file in the sandbox. "
            "Provide the ENTIRE file, not just the changed lines. Use this "
            "to apply your fix. After writing, you should call run_tests "
            "to validate."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path relative to project root.",
                },
                "content": {
                    "type": "string",
                    "description": "The complete new file contents.",
                },
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "run_tests",
        "description": (
            "Run pytest in the sandbox. Returns pass/fail plus the "
            "stdout/stderr of pytest. Use this to verify your fix works."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "test_path": {
                    "type": "string",
                    "description": (
                        "Test path (e.g. "
                        "'tests/test_planted_bugs.py::test_bug1_xxx'). "
                        "Use 'tests/' to run all tests."
                    ),
                }
            },
            "required": ["test_path"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "done",
        "description": (
            "Call this when the fix is complete and tests pass. Provide a "
            "one-line summary of what you changed and why."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "One-line summary of the fix.",
                },
                "modified_files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of files you modified.",
                },
            },
            "required": ["summary", "modified_files"],
            "additionalProperties": False,
        },
    },
]


# ---------------------------------------------------------------------------
# Tool execution
# ---------------------------------------------------------------------------

@dataclass
class ToolEvent:
    """A single tool call + result, suitable for streaming to a UI."""

    iteration: int
    name: str
    arguments: dict
    result: dict
    diff: str | None = None  # populated for write_file


class ToolExecutor:
    """Executes tool calls inside a given sandbox."""

    def __init__(self, sandbox: Sandbox):
        self.sandbox = sandbox
        self._original_contents: dict[str, str] = {}

    def execute(self, name: str, arguments: dict) -> tuple[dict, str | None]:
        """
        Execute a tool call. Returns (result_dict, optional_diff).

        result_dict is what we send back to the LLM as tool output.
        diff is for UI/logs; only populated for write_file.
        """
        if name == "read_file":
            return self._read_file(arguments), None
        if name == "list_files":
            return self._list_files(arguments), None
        if name == "write_file":
            return self._write_file(arguments)
        if name == "run_tests":
            return self._run_tests(arguments), None
        if name == "done":
            return {"status": "marked_done"}, None
        return {"error": f"Unknown tool: {name}"}, None

    # ---- individual tools -------------------------------------------------

    def _read_file(self, args: dict) -> dict:
        path = args.get("path", "")
        try:
            content = self.sandbox.read_file(path)
            if path not in self._original_contents:
                self._original_contents[path] = content
            return {
                "path": path,
                "content": content,
                "line_count": content.count("\n") + 1,
            }
        except FileNotFoundError as e:
            return {"error": str(e), "path": path}

    def _list_files(self, args: dict) -> dict:
        subdir = args.get("subdir", "")
        pattern = args.get("pattern") or "*"
        try:
            files = self.sandbox.list_files(subdir=subdir, pattern=pattern)
            return {
                "subdir": subdir,
                "pattern": pattern,
                "files": files[:200],
                "total": len(files),
                "truncated": len(files) > 200,
            }
        except Exception as e:
            return {"error": str(e)}

    def _write_file(self, args: dict) -> tuple[dict, str]:
        path = args.get("path", "")
        new_content = args.get("content", "")

        if path not in self._original_contents:
            try:
                self._original_contents[path] = self.sandbox.read_file(path)
            except FileNotFoundError:
                self._original_contents[path] = ""

        old_content = self._original_contents[path]
        diff = compute_diff(old_content, new_content, path)
        self.sandbox.write_file(path, new_content)

        return (
            {
                "path": path,
                "bytes_written": len(new_content.encode("utf-8")),
                "lines_changed": _count_diff_lines(diff),
            },
            diff,
        )

    def _run_tests(self, args: dict) -> dict:
        test_path = args.get("test_path") or "tests/"
        result: TestResult = self.sandbox.run_tests(test_path)

        stdout = _trim_pytest_output(result.stdout)
        stderr = result.stderr.strip()[-2000:] if result.stderr else ""

        return {
            "passed": result.passed,
            "return_code": result.return_code,
            "stdout_tail": stdout,
            "stderr_tail": stderr,
            "summary": result.summary(),
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def compute_diff(old: str, new: str, path: str) -> str:
    """Return a unified diff string for display."""
    diff_lines = difflib.unified_diff(
        old.splitlines(keepends=True),
        new.splitlines(keepends=True),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
        n=3,
    )
    return "".join(diff_lines)


def _count_diff_lines(diff: str) -> int:
    return sum(
        1
        for line in diff.splitlines()
        if (line.startswith("+") and not line.startswith("+++"))
        or (line.startswith("-") and not line.startswith("---"))
    )


def _trim_pytest_output(text: str, max_chars: int = 3000) -> str:
    if len(text) <= max_chars:
        return text
    return "... [output truncated, showing last lines] ...\n" + text[-max_chars:]
