"""Shared configuration — single source for all path resolution and env loading."""

from __future__ import annotations

import os
from pathlib import Path


def load_env(path: str = ".env") -> None:
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text().splitlines():
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
