"""Tests for the shared Pantheon consistency validator."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / ".agents" / "scripts" / "skill_validate.py"


def load_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


skill_validate = load_module("test_skill_validate_module", SCRIPT_PATH)


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def make_repo(
    tmp_path: Path,
    *,
    readme_names: list[str] | None = None,
    agents_names: list[str] | None = None,
    rule_names: list[str] | None = None,
    include_eval: bool = True,
    shared_script_name: str | None = None,
    document_shared_script: bool = True,
    agent_script_name: str | None = None,
    document_agent_script: bool = True,
    command_names: list[str] | None = None,
    documented_commands: list[str] | None = None,
) -> Path:
    readme_names = readme_names or ["athena"]
    agents_names = agents_names or ["athena"]
    rule_names = rule_names or ["athena"]
    command_names = command_names or ["plan"]
    documented_commands = documented_commands or command_names

    write(tmp_path / "pyproject.toml", "[project]\nname = 'pantheon'\nversion = '0.1.0'\n")
    write(
        tmp_path / ".agents" / "skills" / "athena" / "SKILL.md",
        """---
name: athena
description: strategist
---

# Athena
"""
        + (f"\n## Utility Scripts\n- `{agent_script_name}`\n" if agent_script_name and document_agent_script else ""),
    )
    if agent_script_name:
        write(
            tmp_path / ".agents" / "skills" / "athena" / "scripts" / agent_script_name,
            "print('helper')\n",
        )

    if include_eval:
        write(tmp_path / "evals" / "athena" / "eval.yaml", 'version: "1"\n')

    shared_readme = "# Shared Scripts\n\n"
    if shared_script_name and document_shared_script:
        shared_readme += f"- `{shared_script_name}`: helper\n"
    write(tmp_path / ".agents" / "scripts" / "README.md", shared_readme)
    if shared_script_name:
        write(tmp_path / ".agents" / "scripts" / shared_script_name, "print('shared')\n")

    readme_lines = [
        "# Pantheon",
        "",
        "## The Pantheon",
        "",
        "| Name | Persona | Model | Use For |",
        "|------|---------|-------|---------|",
    ]
    readme_lines.extend(f"| {name} | persona | model | role |" for name in readme_names)
    readme_lines.extend(["", "## Cursor Commands", ""])
    readme_lines.extend(f"- `/{name}`" for name in documented_commands)
    write(tmp_path / "README.md", "\n".join(readme_lines) + "\n")

    agents_lines = [
        "# AGENTS",
        "",
        "## Roster",
        "",
        "| Agent | Persona | Use For |",
        "|-------|---------|---------|",
    ]
    agents_lines.extend(f"| {name} | persona | role |" for name in agents_names)
    write(tmp_path / "AGENTS.md", "\n".join(agents_lines) + "\n")

    rules_lines = [
        "---",
        'description: "Pantheon roster"',
        "alwaysApply: true",
        "---",
        "",
        "## Roster",
        "",
        "| Agent | Role | Activates when... |",
        "|-------|------|-------------------|",
    ]
    rules_lines.extend(f"| {name} | role | use case |" for name in rule_names)
    write(tmp_path / ".cursor" / "rules" / "pantheon.mdc", "\n".join(rules_lines) + "\n")

    for command_name in command_names:
        write(tmp_path / ".cursor" / "commands" / f"{command_name}.md", f"# /{command_name}\n")

    return tmp_path


class TestSkillValidate:
    def test_validate_repo_passes_for_consistent_repo(self, tmp_path):
        root = make_repo(tmp_path)

        issues = skill_validate.validate_repo(root)

        assert issues == []

    def test_validate_repo_detects_missing_eval(self, tmp_path):
        root = make_repo(tmp_path, include_eval=False)

        issues = skill_validate.validate_repo(root)

        assert any(issue.check == "missing-eval" for issue in issues)

    def test_validate_repo_detects_roster_mismatch(self, tmp_path):
        root = make_repo(tmp_path, readme_names=["athena"], agents_names=["athena"], rule_names=["eris"])

        issues = skill_validate.validate_repo(root)

        assert any(issue.check == "roster-sync" for issue in issues)

    def test_validate_repo_detects_undocumented_shared_script(self, tmp_path):
        root = make_repo(
            tmp_path,
            shared_script_name="helper.py",
            document_shared_script=False,
        )

        issues = skill_validate.validate_repo(root)

        assert any(issue.check == "shared-script-docs" for issue in issues)

    def test_validate_repo_detects_undocumented_agent_script(self, tmp_path):
        root = make_repo(
            tmp_path,
            agent_script_name="helper.py",
            document_agent_script=False,
        )

        issues = skill_validate.validate_repo(root)

        assert any(issue.check == "agent-script-docs" for issue in issues)

    def test_validate_repo_detects_missing_command_docs(self, tmp_path):
        root = make_repo(
            tmp_path,
            command_names=["plan", "review"],
            documented_commands=["plan"],
        )

        issues = skill_validate.validate_repo(root)

        assert any(issue.check == "cursor-command-docs" for issue in issues)
