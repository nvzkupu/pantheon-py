"""Shared configuration — single source for all path resolution and env loading."""

from __future__ import annotations

import os
from pathlib import Path


def repo_root(start: str | Path | None = None) -> Path | None:
    """Return the Pantheon repository root if one can be discovered."""
    search_starts = [Path(start)] if start is not None else [Path.cwd(), Path(__file__)]
    seen: set[Path] = set()

    for base in search_starts:
        current = base.resolve()
        if current.is_file():
            current = current.parent

        for candidate in (current, *current.parents):
            if candidate in seen:
                continue
            seen.add(candidate)
            if (candidate / "pyproject.toml").exists() and (candidate / ".agents" / "skills").is_dir():
                return candidate

    return None


def _resolve_env_path(path: str) -> Path:
    """Resolve an env file path with repo-root awareness for the default case."""
    resolved = Path(path).expanduser()
    if resolved.is_absolute() or path != ".env":
        return resolved

    root = repo_root()
    if root is not None:
        return root / ".env"

    return resolved


def load_env(path: str = ".env") -> None:
    p = _resolve_env_path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if value and len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        if key and not os.environ.get(key):
            os.environ[key] = value


def skills_dir() -> str:
    for var in ("SKILLS_DIR", "AGENTS_DIR"):
        if d := os.environ.get(var):
            return d
    for candidate in (".agents/skills", ".cursor/skills", ".claude/skills"):
        if Path(candidate).is_dir():
            return candidate
    return ".agents/skills"


def gateway_url() -> str:
    for var in ("GATEWAY_URL", "NVIDIA_GATEWAY_URL"):
        if u := os.environ.get(var):
            return u.rstrip("/")
    return "https://integrate.api.nvidia.com/v1"


def api_key() -> str:
    for var in ("API_KEY", "NVIDIA_API_KEY"):
        if k := os.environ.get(var):
            return k
    return ""


def memory_dir() -> str:
    return os.environ.get("MEMORY_DIR", ".memory")


def verbose() -> bool:
    return os.environ.get("VERBOSE", "") in ("1", "true")
