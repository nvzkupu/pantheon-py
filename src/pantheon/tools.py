"""Tool interface, registry, and built-in tools with OS-aware shell execution."""

from __future__ import annotations

import json
import os
import platform
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


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
            return tool.execute(args)
        except Exception as e:
            return f"error: {e}"

    def execute_all(self, calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
        from concurrent.futures import ThreadPoolExecutor

        def run_one(call: dict) -> dict[str, Any]:
            fn = call.get("function", {})
            result = self.execute(fn.get("name", ""), fn.get("arguments", ""))
            return {"role": "tool", "tool_call_id": call.get("id", ""), "content": result}

        with ThreadPoolExecutor() as pool:
            return list(pool.map(run_one, calls))


def _param(desc: str, typ: str = "string") -> dict:
    return {"type": typ, "description": desc}


class ShellExec(Tool):
    def name(self) -> str:
        return "shell_exec"

    def description(self) -> str:
        return "Execute a shell command. Returns stdout/stderr. 60s timeout."

    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "command": _param("Shell command to execute"),
                "workdir": _param("Working directory (optional)"),
            },
            "required": ["command"],
        }

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
        return "Read the contents of a file."

    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {"path": _param("File path to read")},
            "required": ["path"],
        }

    def execute(self, args: dict) -> str:
        try:
            return Path(args["path"]).read_text(encoding="utf-8")
        except Exception as e:
            return f"error: {e}"


class WriteFile(Tool):
    def name(self) -> str:
        return "write_file"

    def description(self) -> str:
        return "Write content to a file, creating parent directories as needed."

    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": _param("File path"),
                "content": _param("Content to write"),
            },
            "required": ["path", "content"],
        }

    def execute(self, args: dict) -> str:
        try:
            p = Path(args["path"])
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(args["content"], encoding="utf-8")
            return f"wrote {len(args['content'])} bytes to {p}"
        except Exception as e:
            return f"error: {e}"


class ListDir(Tool):
    def name(self) -> str:
        return "list_dir"

    def description(self) -> str:
        return "List files and directories. Dirs are suffixed with /."

    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {"path": _param("Directory path")},
            "required": ["path"],
        }

    def execute(self, args: dict) -> str:
        try:
            entries = sorted(Path(args["path"]).iterdir())
            return "\n".join(f"{e.name}/" if e.is_dir() else e.name for e in entries)
        except Exception as e:
            return f"error: {e}"


class SearchFiles(Tool):
    def name(self) -> str:
        return "search_files"

    def description(self) -> str:
        return "Search for files matching a glob pattern (max 100 results)."

    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "pattern": _param("Glob pattern (e.g. '**/*.py')"),
                "root": _param("Root directory (default: '.')"),
            },
            "required": ["pattern"],
        }

    def execute(self, args: dict) -> str:
        root = Path(args.get("root", "."))
        matches = list(root.glob(args["pattern"]))[:100]
        return "\n".join(str(m) for m in matches) if matches else "no matches found"


def builtins() -> Registry:
    r = Registry()
    for t in (ShellExec(), ReadFile(), WriteFile(), ListDir(), SearchFiles()):
        r.register(t)
    return r
