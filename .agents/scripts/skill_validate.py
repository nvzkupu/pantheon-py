#!/usr/bin/env python3
"""Validate Pantheon skill, script, and roster consistency."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class SkillRecord:
    """Discovered skill metadata needed for consistency checks."""

    name: str
    dir_name: str
    skill_path: Path


@dataclass(frozen=True)
class Issue:
    """A consistency issue detected by validation."""

    severity: str
    check: str
    location: str
    message: str


def find_repo_root(start: str | Path | None = None) -> Path:
    """Walk upward until the Pantheon repository root is found."""
    current = Path(start or __file__).resolve()
    if current.is_file():
        current = current.parent

    for candidate in (current, *current.parents):
        if (candidate / "pyproject.toml").exists() and (candidate / ".agents" / "skills").is_dir():
            return candidate
    raise SystemExit("Could not determine repository root from the current path")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def split_frontmatter(text: str) -> tuple[str, str]:
    """Split YAML frontmatter from markdown body."""
    stripped = text.strip()
    if not stripped.startswith("---"):
        return "", stripped
    rest = stripped[3:]
    marker = rest.find("\n---")
    if marker < 0:
        return "", stripped
    return rest[:marker].strip(), rest[marker + 4 :].strip()


def parse_skill(skill_path: Path) -> SkillRecord:
    """Read a skill file and return the discovered name."""
    fm_text, _body = split_frontmatter(read_text(skill_path))
    if not fm_text:
        raise ValueError(f"{skill_path}: no YAML frontmatter found")
    data = yaml.safe_load(fm_text) or {}
    name = data.get("name") or skill_path.parent.name
    return SkillRecord(name=name, dir_name=skill_path.parent.name, skill_path=skill_path)


def discover_skills(root: Path) -> tuple[list[SkillRecord], list[Issue]]:
    """Discover skill files and collect duplicate-name issues."""
    skills_dir = root / ".agents" / "skills"
    issues: list[Issue] = []
    seen: dict[str, Path] = {}
    records: list[SkillRecord] = []

    for skill_path in sorted(skills_dir.glob("*/SKILL.md")):
        try:
            record = parse_skill(skill_path)
        except (ValueError, yaml.YAMLError) as exc:
            issues.append(
                Issue(
                    severity="error",
                    check="skill-parse",
                    location=str(skill_path.relative_to(root)),
                    message=str(exc),
                )
            )
            continue
        previous = seen.get(record.name)
        if previous is not None:
            issues.append(
                Issue(
                    severity="error",
                    check="duplicate-skill-name",
                    location=str(skill_path.relative_to(root)),
                    message=(
                        f"skill name '{record.name}' is duplicated; already used by "
                        f"{previous.relative_to(root)}"
                    ),
                )
            )
        else:
            seen[record.name] = skill_path
        records.append(record)

    return records, issues


def extract_table_names(text: str, heading: str) -> list[str]:
    """Extract the first column from a markdown table under a heading."""
    lines = text.splitlines()
    start_idx = next((idx for idx, line in enumerate(lines) if line.strip() == heading), None)
    if start_idx is None:
        return []

    rows: list[str] = []
    in_table = False
    for line in lines[start_idx + 1 :]:
        stripped = line.strip()
        if stripped.startswith("|"):
            rows.append(stripped)
            in_table = True
            continue
        if in_table:
            break

    names: list[str] = []
    for row in rows:
        cells = [cell.strip() for cell in row.strip("|").split("|")]
        if not cells:
            continue
        first = cells[0]
        if not first:
            continue
        if first.lower() in {"name", "agent"}:
            continue
        if set(first) <= {"-"}:
            continue
        names.append(first)
    return names


def compare_sets(
    *,
    expected: set[str],
    actual: set[str],
    check: str,
    location: str,
    subject: str,
) -> list[Issue]:
    """Return missing/extra set-comparison issues."""
    issues: list[Issue] = []
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing:
        issues.append(
            Issue(
                severity="error",
                check=check,
                location=location,
                message=f"{subject} is missing: {', '.join(missing)}",
            )
        )
    if extra:
        issues.append(
            Issue(
                severity="error",
                check=check,
                location=location,
                message=f"{subject} has unexpected entries: {', '.join(extra)}",
            )
        )
    return issues


def validate_rosters(root: Path, skills: list[SkillRecord]) -> list[Issue]:
    """Ensure project rosters match the actual skill set."""
    expected = {skill.name for skill in skills}
    roster_specs = {
        Path("README.md"): "## The Pantheon",
        Path("AGENTS.md"): "## Roster",
        Path(".cursor/rules/pantheon.mdc"): "## Roster",
    }

    issues: list[Issue] = []
    for relative_path, heading in roster_specs.items():
        file_path = root / relative_path
        actual = set(extract_table_names(read_text(file_path), heading))
        issues.extend(
            compare_sets(
                expected=expected,
                actual=actual,
                check="roster-sync",
                location=str(relative_path),
                subject="roster",
            )
        )
    return issues


def validate_evals(root: Path, skills: list[SkillRecord]) -> list[Issue]:
    """Ensure every skill has a matching eval."""
    issues: list[Issue] = []
    for skill in skills:
        eval_path = root / "evals" / skill.name / "eval.yaml"
        if not eval_path.exists():
            issues.append(
                Issue(
                    severity="error",
                    check="missing-eval",
                    location=str(skill.skill_path.relative_to(root)),
                    message=f"skill '{skill.name}' has no matching eval at {eval_path.relative_to(root)}",
                )
            )
    return issues


def validate_shared_script_docs(root: Path) -> list[Issue]:
    """Ensure shared utilities are listed in the shared script index."""
    scripts_dir = root / ".agents" / "scripts"
    if not scripts_dir.exists():
        return []

    script_files = sorted(path for path in scripts_dir.glob("*.py") if path.is_file())
    if not script_files:
        return []

    readme_path = scripts_dir / "README.md"
    if not readme_path.exists():
        return [
            Issue(
                severity="error",
                check="shared-script-docs",
                location=str(scripts_dir.relative_to(root)),
                message="shared script directory is missing README.md",
            )
        ]

    readme_text = read_text(readme_path)
    issues: list[Issue] = []
    for script in script_files:
        if script.name not in readme_text:
            issues.append(
                Issue(
                    severity="error",
                    check="shared-script-docs",
                    location=str(script.relative_to(root)),
                    message="shared script is not documented in .agents/scripts/README.md",
                )
            )
    return issues


def validate_agent_script_docs(root: Path, skills: list[SkillRecord]) -> list[Issue]:
    """Ensure agent-local scripts are documented in their owning skill docs."""
    issues: list[Issue] = []
    for skill in skills:
        script_dir = skill.skill_path.parent / "scripts"
        if not script_dir.is_dir():
            continue

        doc_text = read_text(skill.skill_path)
        reference_path = skill.skill_path.parent / "reference.md"
        if reference_path.exists():
            doc_text += "\n" + read_text(reference_path)

        for script_path in sorted(script_dir.glob("*.py")):
            if script_path.name not in doc_text:
                issues.append(
                    Issue(
                        severity="error",
                        check="agent-script-docs",
                        location=str(script_path.relative_to(root)),
                        message=(
                            "agent script is not mentioned in the owning skill's "
                            "SKILL.md or reference.md"
                        ),
                    )
                )
    return issues


def validate_readme_commands(root: Path) -> list[Issue]:
    """Ensure README advertises the available Cursor slash commands."""
    commands_dir = root / ".cursor" / "commands"
    if not commands_dir.is_dir():
        return []

    readme_text = read_text(root / "README.md")
    issues: list[Issue] = []
    for command_path in sorted(commands_dir.glob("*.md")):
        command_name = f"/{command_path.stem}"
        if command_name not in readme_text:
            issues.append(
                Issue(
                    severity="error",
                    check="cursor-command-docs",
                    location=str(command_path.relative_to(root)),
                    message=f"README.md does not mention the {command_name} slash command",
                )
            )
    return issues


def validate_repo(root: Path) -> list[Issue]:
    """Run all operational consistency checks for the repository."""
    skills, issues = discover_skills(root)
    issues.extend(validate_rosters(root, skills))
    issues.extend(validate_evals(root, skills))
    issues.extend(validate_shared_script_docs(root))
    issues.extend(validate_agent_script_docs(root, skills))
    issues.extend(validate_readme_commands(root))
    return sorted(issues, key=lambda item: (item.severity, item.check, item.location, item.message))


def build_payload(root: Path, issues: list[Issue]) -> dict[str, object]:
    """Construct the machine-readable output payload."""
    error_count = sum(1 for issue in issues if issue.severity == "error")
    warning_count = sum(1 for issue in issues if issue.severity == "warning")
    return {
        "root": str(root),
        "summary": {
            "issues": len(issues),
            "errors": error_count,
            "warnings": warning_count,
        },
        "issues": [asdict(issue) for issue in issues],
    }


def print_text(payload: dict[str, object]) -> None:
    """Emit a human-readable report."""
    summary = payload["summary"]
    print(
        "summary:"
        f" issues={summary['issues']}"
        f" errors={summary['errors']}"
        f" warnings={summary['warnings']}"
    )
    for issue in payload["issues"]:
        print(
            f"{issue['severity']}\t{issue['check']}\t{issue['location']}\t{issue['message']}"
        )


def cmd_validate(args: argparse.Namespace) -> int:
    root = find_repo_root(args.root)
    issues = validate_repo(root)
    payload = build_payload(root, issues)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print_text(payload)
    return 1 if payload["summary"]["errors"] else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    validate = sub.add_parser("validate", help="Validate Pantheon operational consistency")
    validate.add_argument(
        "--root",
        help="Override the repository root instead of discovering it automatically",
    )
    validate.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of tab-separated text",
    )
    validate.set_defaults(func=cmd_validate)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
