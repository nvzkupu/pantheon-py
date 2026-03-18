#!/usr/bin/env python3
"""Scan a tree for likely secrets and dangerous dynamic-execution patterns."""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class ScanRule:
    """A single scanner rule."""

    rule_id: str
    description: str
    pattern: re.Pattern[str]
    redact_preview: bool = False


@dataclass(frozen=True)
class Finding:
    """A single scan finding."""

    rule_id: str
    path: str
    line: int
    description: str
    preview: str


DEFAULT_EXCLUDE_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    "__pycache__",
    "node_modules",
    ".venv",
    "dist",
    "build",
}

DEFAULT_RULES = [
    ScanRule(
        rule_id="private-key-block",
        description="private key material detected",
        pattern=re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
        redact_preview=True,
    ),
    ScanRule(
        rule_id="secret-assignment",
        description="possible hardcoded secret assignment",
        pattern=re.compile(
            r"(?i)\b(password|secret|token|api[_-]?key|access[_-]?key|private[_-]?key)\b.{0,20}[:=].+"
        ),
        redact_preview=True,
    ),
    ScanRule(
        rule_id="dangerous-eval",
        description="dynamic eval detected",
        pattern=re.compile(r"\beval\s*\("),
    ),
    ScanRule(
        rule_id="dangerous-exec",
        description="dynamic exec detected",
        pattern=re.compile(r"\bexec\s*\("),
    ),
]


def should_skip(path: Path, root: Path, exclude_patterns: list[str]) -> bool:
    rel_path = path.relative_to(root).as_posix()
    if any(part in DEFAULT_EXCLUDE_PARTS for part in path.parts):
        return True
    return any(fnmatch.fnmatch(rel_path, pattern) for pattern in exclude_patterns)


def is_text_file(path: Path, max_bytes: int) -> bool:
    try:
        with path.open("rb") as handle:
            chunk = handle.read(max_bytes + 1)
    except OSError:
        return False
    if len(chunk) > max_bytes:
        return False
    return b"\x00" not in chunk


def sanitize_preview(line: str, *, redact: bool) -> str:
    stripped = line.strip()
    if not redact:
        return stripped[:160]
    if "PRIVATE KEY" in stripped:
        return "[redacted private key material]"
    if ":" in stripped or "=" in stripped:
        return re.sub(r"([:=]\s*).+$", r"\1[redacted]", stripped)[:160]
    return "[redacted]"


def iter_files(root: Path, exclude_patterns: list[str], max_bytes: int) -> list[Path]:
    if root.is_file():
        return [root] if is_text_file(root, max_bytes) else []

    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if should_skip(path, root, exclude_patterns):
            continue
        if is_text_file(path, max_bytes):
            files.append(path)
    return files


def scan_file(path: Path, base: Path, rules: list[ScanRule]) -> list[Finding]:
    findings: list[Finding] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return findings

    relative_path = path.relative_to(base).as_posix() if base.is_dir() else path.name
    for line_no, line in enumerate(lines, start=1):
        for rule in rules:
            if not rule.pattern.search(line):
                continue
            findings.append(
                Finding(
                    rule_id=rule.rule_id,
                    path=relative_path,
                    line=line_no,
                    description=rule.description,
                    preview=sanitize_preview(line, redact=rule.redact_preview),
                )
            )
    return findings


def scan_path(
    target: Path,
    *,
    exclude_patterns: list[str] | None = None,
    max_bytes: int = 1024 * 1024,
) -> list[Finding]:
    """Scan a file or directory tree and return findings."""
    exclude_patterns = exclude_patterns or []
    base = target if target.is_dir() else target.parent
    findings: list[Finding] = []
    for path in iter_files(target, exclude_patterns, max_bytes):
        findings.extend(scan_file(path, base, DEFAULT_RULES))
    return findings


def build_payload(target: Path, findings: list[Finding]) -> dict[str, object]:
    by_rule: dict[str, int] = {}
    for finding in findings:
        by_rule[finding.rule_id] = by_rule.get(finding.rule_id, 0) + 1
    return {
        "target": str(target),
        "summary": {
            "findings": len(findings),
            "rules": by_rule,
        },
        "findings": [asdict(finding) for finding in findings],
    }


def print_text(payload: dict[str, object]) -> None:
    summary = payload["summary"]
    print(f"summary: findings={summary['findings']}")
    for rule_id, count in sorted(summary["rules"].items()):
        print(f"rule\t{rule_id}\t{count}")
    for finding in payload["findings"]:
        print(
            f"finding\t{finding['rule_id']}\t{finding['path']}:{finding['line']}\t{finding['preview']}"
        )


def cmd_scan(args: argparse.Namespace) -> int:
    target = Path(args.target).resolve()
    findings = scan_path(
        target,
        exclude_patterns=args.exclude,
        max_bytes=args.max_bytes,
    )
    payload = build_payload(target, findings)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print_text(payload)
    return 1 if findings else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="Scan a path for likely secrets or dangerous patterns")
    scan.add_argument("target", help="File or directory to scan")
    scan.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="Relative glob to exclude; may be supplied multiple times",
    )
    scan.add_argument(
        "--max-bytes",
        type=int,
        default=1024 * 1024,
        help="Skip files larger than this many bytes",
    )
    scan.add_argument("--json", action="store_true", help="Emit JSON instead of text output")
    scan.set_defaults(func=cmd_scan)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
