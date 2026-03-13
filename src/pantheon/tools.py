"""Tool interface, registry, and built-in tools with OS-aware shell execution."""

from __future__ import annotations

import json
import logging
import os
import platform
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)
_MAX_READ_SIZE = 10 * 1024 * 1024


class Tool(ABC):
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def description(self) -> str: ...

    @abstractmethod
    def parameters(self) -> dict[str, Any]: ...

    @abstractmethod
    def execute(self, args: dict[str, Any]) -> str: ...

    def definition(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name(),
                "description": self.description(),
                "parameters": self.parameters(),
                "strict": True,
            },
        }


class Registry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name()] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def definitions(self) -> list[dict[str, Any]]:
        return [t.definition() for t in self._tools.values()]

    def execute(self, name: str, args_json: str) -> str:
        tool = self._tools.get(name)
        if not tool:
            return f"error: unknown tool '{name}'"
        try:
            args = json.loads(args_json) if args_json else {}
            missing = check_required(tool.parameters(), args)
            if missing:
                fields = ", ".join(missing)
                return f"error: missing required fields for '{name}': {fields}"
            return tool.execute(args)
        except (
            json.JSONDecodeError, KeyError, ValueError,
            OSError, subprocess.SubprocessError,
        ) as e:
            _log.warning("tool '%s' failed: %s", name, e)
            return f"error: {e}"

    def execute_all(self, calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
        from concurrent.futures import ThreadPoolExecutor

        def run_one(call: dict) -> dict[str, Any]:
            fn = call.get("function", {})
            result = self.execute(fn.get("name", ""), fn.get("arguments", ""))
            return {
                "role": "tool",
                "tool_call_id": call.get("id", ""),
                "content": result,
            }

        with ThreadPoolExecutor() as pool:
            return list(pool.map(run_one, calls))


def param(desc: str, typ: str = "string") -> dict:
    return {"type": typ, "description": desc}


def check_required(schema: dict, args: dict) -> list[str]:
    """Return list of required fields missing from args."""
    required = schema.get("required", [])
    return [f for f in required if f not in args or args[f] is None]


def strict_schema(properties: dict, required: list[str]) -> dict:
    """Build a JSON Schema object with additionalProperties: false for strict mode."""
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


class ShellExec(Tool):
    def name(self) -> str:
        return "shell_exec"

    def description(self) -> str:
        return (
            "Execute a shell command in the system shell"
            " and return combined stdout/stderr output."
            " Use this tool to run build commands, install"
            " packages, query system state, or perform any"
            " operation available via the command line."
            " The command times out after 60 seconds;"
            " long-running processes will be killed."
            " On Windows runs via cmd.exe; on Unix uses"
            " the user's default shell."
            " Returns '(no output)' when the command"
            " succeeds but produces no output."
        )

    def parameters(self) -> dict:
        return strict_schema({
            "command": param(
                "The shell command to execute,"
                " e.g. 'pip install requests' or 'ls -la'",
            ),
            "workdir": param(
                "Working directory for the command."
                " Pass empty string for current directory",
            ),
        }, ["command", "workdir"])

    def execute(self, args: dict) -> str:
        cmd = args["command"]
        cwd = args.get("workdir") or None

        if platform.system() == "Windows":
            shell_cmd = ["cmd.exe", "/c", cmd]
        else:
            shell = os.environ.get("SHELL", "/bin/sh")
            shell_cmd = [shell, "-c", cmd]

        try:
            result = subprocess.run(
                shell_cmd, capture_output=True, text=True,
                timeout=60, cwd=cwd)
            output = (result.stdout + result.stderr).strip()
            if result.returncode != 0:
                return f"{output}\nexit code: {result.returncode}"
            return output or "(no output)"
        except subprocess.TimeoutExpired:
            return "error: command timed out after 60s"


class ReadFile(Tool):
    def name(self) -> str:
        return "read_file"

    def description(self) -> str:
        return (
            "Read the full contents of a file and return"
            " it as a UTF-8 string. Use this tool when you"
            " need to inspect source code, configuration"
            " files, or any text file. Returns a descriptive"
            " error if the file does not exist or cannot be"
            " read. Does not support binary files; use"
            " shell_exec for binary operations."
        )

    def parameters(self) -> dict:
        return strict_schema({
            "path": param(
                "Absolute or relative file path to read,"
                " e.g. 'src/main.py'",
            ),
        }, ["path"])

    def execute(self, args: dict) -> str:
        try:
            p = Path(args["path"])
            if p.stat().st_size > _MAX_READ_SIZE:
                return "error: file exceeds 10 MB limit"
            return p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            return f"error: {e}"


class WriteFile(Tool):
    def name(self) -> str:
        return "write_file"

    def description(self) -> str:
        return (
            "Write text content to a file, creating any"
            " missing parent directories automatically."
            " Use this tool to create new files or overwrite"
            " existing ones with the provided content."
            " The file is written with UTF-8 encoding."
            " Returns a confirmation with the byte count"
            " written, or an error if the write fails."
        )

    def parameters(self) -> dict:
        return strict_schema({
            "path": param(
                "Absolute or relative file path to write,"
                " e.g. 'output/result.json'",
            ),
            "content": param(
                "The full text content to write to the file",
            ),
        }, ["path", "content"])

    def execute(self, args: dict) -> str:
        try:
            p = Path(args["path"])
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(args["content"], encoding="utf-8")
            return f"wrote {len(args['content'])} bytes to {p}"
        except OSError as e:
            return f"error: {e}"


class ListDir(Tool):
    def name(self) -> str:
        return "list_dir"

    def description(self) -> str:
        return (
            "List all files and subdirectories in a"
            " directory, one entry per line. Directory"
            " entries are suffixed with '/' to distinguish"
            " them from files. Use this tool to explore"
            " project structure or verify that expected"
            " files exist. Returns an error if the path"
            " does not exist or is not a directory."
        )

    def parameters(self) -> dict:
        return strict_schema({
            "path": param(
                "Absolute or relative path to the"
                " directory to list, e.g. 'src/'",
            ),
        }, ["path"])

    def execute(self, args: dict) -> str:
        try:
            entries = sorted(Path(args["path"]).iterdir())
            return "\n".join(f"{e.name}/" if e.is_dir() else e.name for e in entries)
        except OSError as e:
            return f"error: {e}"


class SearchFiles(Tool):
    def name(self) -> str:
        return "search_files"

    def description(self) -> str:
        return (
            "Recursively search for files matching a glob"
            " pattern, starting from a root directory."
            " Returns matching file paths (one per line),"
            " capped at 100 results. Supports Python glob"
            " syntax including '**/' for recursive matching."
            " Returns 'no matches found' if nothing matches."
        )

    def parameters(self) -> dict:
        return strict_schema({
            "pattern": param(
                "Glob pattern for matching files,"
                " e.g. '**/*.py', '*.test.js'",
            ),
            "root": param(
                "Root directory to search from."
                " Pass empty string for current directory",
            ),
        }, ["pattern", "root"])

    def execute(self, args: dict) -> str:
        root = Path(args.get("root", "."))
        matches = list(root.glob(args["pattern"]))[:100]
        return "\n".join(str(m) for m in matches) if matches else "no matches found"


def builtins() -> Registry:
    r = Registry()
    for t in (ShellExec(), ReadFile(), WriteFile(), ListDir(), SearchFiles()):
        r.register(t)
    return r
