"""SKILL.md parser following the agentskills.io specification."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class Metadata:
    persona: str = ""
    model: str = ""
    temperature: float = 0.0
    max_tokens: int = 0
    max_iterations: int = 0
    tools: list[str] = field(default_factory=list)
    delegates: list[str] = field(default_factory=list)


@dataclass
class Skill:
    name: str
    description: str
    body: str
    path: str
    license: str = ""
    metadata: Metadata = field(default_factory=Metadata)

    @property
    def persona(self) -> str:
        return self.metadata.persona

    @property
    def model(self) -> str:
        return self.metadata.model or "gpt-4o"

    @property
    def temperature(self) -> float:
        return self.metadata.temperature or 0.7

    @property
    def max_tokens(self) -> int:
        return self.metadata.max_tokens or 4096

    @property
    def max_iterations(self) -> int:
        return self.metadata.max_iterations or 10

    @property
    def tool_names(self) -> list[str]:
        return self.metadata.tools

    @property
    def delegate_names(self) -> list[str]:
        return self.metadata.delegates


def split_frontmatter(text: str) -> tuple[str, str]:
    """Split YAML frontmatter from markdown body. Returns (yaml_str, body)."""
    text = text.strip()
    if not text.startswith("---"):
        return "", text

    rest = text[3:]
    idx = rest.find("\n---")
    if idx < 0:
        return "", text

    fm = rest[:idx].strip()
    body = rest[idx + 4:].strip()
    return fm, body


def parse(path: str | Path) -> Skill:
    """Parse a SKILL.md file into a Skill object."""
    path = Path(path)
    return parse_text(path.read_text(encoding="utf-8"), str(path))


def parse_text(text: str, path: str = "<string>") -> Skill:
    """Parse SKILL.md content from a string."""
    fm_str, body = split_frontmatter(text)

    if not fm_str:
        raise ValueError(f"skill {path}: no YAML frontmatter found")

    data: dict[str, Any] = yaml.safe_load(fm_str) or {}

    description = data.get("description", "")
    if not description:
        raise ValueError(f"skill {path}: missing required field 'description'")

    name = data.get("name", "")
    if not name:
        name = Path(path).parent.name

    raw_meta = data.get("metadata", {}) or {}
    metadata = Metadata(
        persona=raw_meta.get("persona", ""),
        model=raw_meta.get("model", ""),
        temperature=float(raw_meta.get("temperature", 0)),
        max_tokens=int(raw_meta.get("max_tokens", 0)),
        max_iterations=int(raw_meta.get("max_iterations", 0)),
        tools=raw_meta.get("tools", []) or [],
        delegates=raw_meta.get("delegates", []) or [],
    )

    return Skill(
        name=name,
        description=description,
        body=body,
        path=path,
        license=data.get("license", ""),
        metadata=metadata,
    )


def discover(directory: str | Path) -> list[Skill]:
    """Walk a skills directory and return all valid skills found."""
    d = Path(directory)
    if not d.is_dir():
        return []

    skills = []
    for entry in sorted(d.iterdir()):
        if not entry.is_dir():
            continue
        skill_path = entry / "SKILL.md"
        if not skill_path.exists():
            continue
        try:
            skills.append(parse(skill_path))
        except (ValueError, yaml.YAMLError) as e:
            import sys
            print(f"warning: skipping {skill_path}: {e}", file=sys.stderr)
    return skills


def discover_map(directory: str | Path) -> dict[str, Skill]:
    """Like discover() but returns a dict keyed by skill name."""
    return {s.name: s for s in discover(directory)}
