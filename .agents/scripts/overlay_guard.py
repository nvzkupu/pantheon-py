#!/usr/bin/env python3
"""Plan and apply safe local overlays without overwriting existing files."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

DEFAULT_EXCLUDED_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    "__pycache__",
}


@dataclass(frozen=True)
class OverlayDecision:
    path: str
    action: str
    reason: str
    source_sha256: str
    target_sha256: str | None
    source_size: int
    target_size: int | None


def sha256_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def matches_patterns(rel_path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(rel_path, pattern) for pattern in patterns)


def should_skip(rel_path: str, exclude_patterns: list[str]) -> bool:
    if any(part in DEFAULT_EXCLUDED_PARTS for part in Path(rel_path).parts):
        return True
    return matches_patterns(rel_path, exclude_patterns)


def iter_source_files(
    source_root: Path,
    include_patterns: list[str],
    exclude_patterns: list[str],
) -> Iterable[tuple[str, Path]]:
    if not source_root.is_dir():
        raise SystemExit(f"Source directory does not exist: {source_root}")

    for path in sorted(source_root.rglob("*")):
        if not path.is_file():
            continue
        rel_path = path.relative_to(source_root).as_posix()
        if include_patterns and not matches_patterns(rel_path, include_patterns):
            continue
        if should_skip(rel_path, exclude_patterns):
            continue
        yield rel_path, path


def build_plan(
    source_root: Path,
    target_root: Path,
    include_patterns: list[str] | None = None,
    exclude_patterns: list[str] | None = None,
) -> list[OverlayDecision]:
    include_patterns = include_patterns or []
    exclude_patterns = exclude_patterns or []

    decisions: list[OverlayDecision] = []
    for rel_path, source_path in iter_source_files(
        source_root,
        include_patterns,
        exclude_patterns,
    ):
        target_path = target_root / rel_path
        source_size = source_path.stat().st_size
        source_sha = sha256_digest(source_path)

        if not target_path.exists():
            decisions.append(
                OverlayDecision(
                    path=rel_path,
                    action="create-safe",
                    reason="target path does not exist",
                    source_sha256=source_sha,
                    target_sha256=None,
                    source_size=source_size,
                    target_size=None,
                )
            )
            continue

        if not target_path.is_file():
            decisions.append(
                OverlayDecision(
                    path=rel_path,
                    action="review-required",
                    reason="target path exists and is not a regular file",
                    source_sha256=source_sha,
                    target_sha256=None,
                    source_size=source_size,
                    target_size=None,
                )
            )
            continue

        target_size = target_path.stat().st_size
        target_sha = sha256_digest(target_path)
        if source_sha == target_sha:
            decisions.append(
                OverlayDecision(
                    path=rel_path,
                    action="identical",
                    reason="source and target already match",
                    source_sha256=source_sha,
                    target_sha256=target_sha,
                    source_size=source_size,
                    target_size=target_size,
                )
            )
            continue

        decisions.append(
            OverlayDecision(
                path=rel_path,
                action="review-required",
                reason="target file already exists with different content",
                source_sha256=source_sha,
                target_sha256=target_sha,
                source_size=source_size,
                target_size=target_size,
            )
        )

    return decisions


def summarize(decisions: list[OverlayDecision]) -> dict[str, int]:
    summary = {"create-safe": 0, "identical": 0, "review-required": 0}
    for decision in decisions:
        summary[decision.action] = summary.get(decision.action, 0) + 1
    summary["total"] = len(decisions)
    return summary


def payload_for(
    source_root: Path,
    target_root: Path,
    decisions: list[OverlayDecision],
) -> dict[str, object]:
    return {
        "source_root": str(source_root),
        "target_root": str(target_root),
        "summary": summarize(decisions),
        "decisions": [asdict(item) for item in decisions],
    }


def render_review_markdown(
    source_root: Path,
    target_root: Path,
    decisions: list[OverlayDecision],
) -> str:
    summary = summarize(decisions)
    review_required = [item for item in decisions if item.action == "review-required"]
    create_safe = [item for item in decisions if item.action == "create-safe"]
    identical = [item for item in decisions if item.action == "identical"]

    lines = [
        "# Overlay Review Package",
        "",
        "## Scope",
        f"- Source: `{source_root}`",
        f"- Target: `{target_root}`",
        f"- Total files considered: {summary['total']}",
        f"- Create-safe: {summary['create-safe']}",
        f"- Review-required: {summary['review-required']}",
        f"- Identical: {summary['identical']}",
        "",
        "## Create-safe Paths",
    ]

    if create_safe:
        lines.extend(f"- `{item.path}`" for item in create_safe)
    else:
        lines.append("- None")

    lines.extend(["", "## Review-required Paths"])
    if review_required:
        lines.extend(f"- `{item.path}`: {item.reason}" for item in review_required)
    else:
        lines.append("- None")

    lines.extend(["", "## Identical Paths"])
    if identical:
        lines.extend(f"- `{item.path}`" for item in identical)
    else:
        lines.append("- None")

    return "\n".join(lines) + "\n"


def write_outputs(
    manifest_path: str | None,
    review_path: str | None,
    source_root: Path,
    target_root: Path,
    decisions: list[OverlayDecision],
) -> None:
    if manifest_path:
        Path(manifest_path).write_text(
            json.dumps(payload_for(source_root, target_root, decisions), indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
    if review_path:
        Path(review_path).write_text(
            render_review_markdown(source_root, target_root, decisions),
            encoding="utf-8",
        )


def copy_create_safe_files(
    source_root: Path,
    target_root: Path,
    decisions: list[OverlayDecision],
) -> list[str]:
    copied: list[str] = []
    for item in decisions:
        if item.action != "create-safe":
            continue
        source_path = source_root / item.path
        target_path = target_root / item.path
        if target_path.exists():
            raise RuntimeError(f"Refusing overwrite during copy-missing: {item.path}")
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target_path)
        copied.append(item.path)
    return copied


def print_text_summary(decisions: list[OverlayDecision]) -> None:
    summary = summarize(decisions)
    print(
        "summary:"
        f" create-safe={summary['create-safe']}"
        f" review-required={summary['review-required']}"
        f" identical={summary['identical']}"
    )
    for item in decisions:
        print(f"{item.action}\t{item.path}\t{item.reason}")


def add_plan_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("source", help="Source directory to overlay from")
    parser.add_argument("target", help="Target directory to inspect or copy into")
    parser.add_argument(
        "--include",
        action="append",
        default=[],
        help="Relative glob to include; may be supplied multiple times",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="Relative glob to exclude; may be supplied multiple times",
    )
    parser.add_argument(
        "--manifest",
        help="Write the JSON plan to this path",
    )
    parser.add_argument(
        "--review",
        help="Write a markdown review package to this path",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON to stdout instead of a text summary",
    )


def cmd_plan(args: argparse.Namespace) -> int:
    source_root = Path(args.source).resolve()
    target_root = Path(args.target).resolve()
    decisions = build_plan(source_root, target_root, args.include, args.exclude)
    write_outputs(args.manifest, args.review, source_root, target_root, decisions)

    if args.json:
        print(json.dumps(payload_for(source_root, target_root, decisions), indent=2, sort_keys=True))
    else:
        print_text_summary(decisions)
    return 0


def cmd_copy_missing(args: argparse.Namespace) -> int:
    source_root = Path(args.source).resolve()
    target_root = Path(args.target).resolve()
    decisions = build_plan(source_root, target_root, args.include, args.exclude)
    copied = copy_create_safe_files(source_root, target_root, decisions)
    write_outputs(args.manifest, args.review, source_root, target_root, decisions)

    payload = payload_for(source_root, target_root, decisions)
    payload["copied"] = copied
    payload["copied_count"] = len(copied)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print_text_summary(decisions)
        print(f"copied:\t{len(copied)}")
        for rel_path in copied:
            print(f"copied-file\t{rel_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan", help="Classify source files against an existing target tree")
    add_plan_arguments(plan)
    plan.set_defaults(func=cmd_plan)

    copy_missing = sub.add_parser(
        "copy-missing",
        help="Copy only files whose target path does not yet exist",
    )
    add_plan_arguments(copy_missing)
    copy_missing.set_defaults(func=cmd_copy_missing)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return args.func(args)
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    raise SystemExit(main())
