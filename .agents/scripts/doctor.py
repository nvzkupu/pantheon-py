#!/usr/bin/env python3
"""Run environment and workspace health checks for the Pantheon."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class CheckResult:
    """A single doctor check outcome."""

    name: str
    status: str
    message: str
    details: dict[str, object] | None = None


def find_repo_root(start: str | Path | None = None) -> Path | None:
    """Walk upward until the Pantheon repository root is found."""
    current = Path(start or Path.cwd()).resolve()
    if current.is_file():
        current = current.parent

    for candidate in (current, *current.parents):
        if (candidate / "pyproject.toml").exists() and (candidate / ".agents" / "skills").is_dir():
            return candidate
    return None


def _env_value(names: tuple[str, ...]) -> str | None:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return None


def load_env_file(root: Path | None) -> bool:
    """Load repo-local .env values into the process if present.

    Existing environment variables win. Returns True when a .env file was found.
    """
    if root is None:
        return False

    env_path = root / ".env"
    if not env_path.exists():
        return False

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value and len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value

    return True


def check_repo_root(root: Path | None) -> CheckResult:
    if root is None:
        return CheckResult(
            name="repo-root",
            status="error",
            message="could not discover a Pantheon repository root from the current directory",
        )
    return CheckResult(
        name="repo-root",
        status="ok",
        message="discovered Pantheon repository root",
        details={"root": str(root)},
    )


def check_env_file(root: Path | None) -> CheckResult:
    if root is None:
        return CheckResult(
            name="env-file",
            status="warn",
            message="skipping .env check because the repository root is unknown",
        )

    env_path = root / ".env"
    if env_path.exists():
        return CheckResult(
            name="env-file",
            status="ok",
            message="found repository .env file",
            details={"path": str(env_path)},
        )
    return CheckResult(
        name="env-file",
        status="warn",
        message="repository .env file not found",
        details={"expected_path": str(env_path)},
    )


def check_import_resolution(root: Path | None) -> CheckResult:
    spec = importlib.util.find_spec("pantheon")
    if spec is None:
        return CheckResult(
            name="pantheon-import",
            status="warn",
            message="could not resolve the pantheon package on sys.path",
        )

    resolved = None
    if spec.origin:
        resolved = Path(spec.origin).resolve()
    elif spec.submodule_search_locations:
        resolved = Path(next(iter(spec.submodule_search_locations))).resolve()

    if resolved is None:
        return CheckResult(
            name="pantheon-import",
            status="warn",
            message="pantheon package resolved without a concrete filesystem path",
        )

    details = {"resolved": str(resolved)}
    if root is None:
        return CheckResult(
            name="pantheon-import",
            status="warn",
            message="pantheon import resolved, but repository root is unknown",
            details=details,
        )

    expected = (root / "src" / "pantheon").resolve()
    details["expected"] = str(expected)
    if resolved == expected or resolved.parent == expected:
        return CheckResult(
            name="pantheon-import",
            status="ok",
            message="pantheon imports resolve to this repository",
            details=details,
        )

    return CheckResult(
        name="pantheon-import",
        status="warn",
        message="pantheon imports resolve to a different location than this repository",
        details=details,
    )


def check_command(name: str, *, required: bool) -> CheckResult:
    path = shutil.which(name)
    if path:
        return CheckResult(
            name=f"command:{name}",
            status="ok",
            message=f"found command '{name}'",
            details={"path": path},
        )

    return CheckResult(
        name=f"command:{name}",
        status="error" if required else "warn",
        message=f"command '{name}' is not available on PATH",
    )


def check_env_group(label: str, names: tuple[str, ...], *, required: bool) -> CheckResult:
    value = _env_value(names)
    if value is not None:
        return CheckResult(
            name=f"env:{label}",
            status="ok",
            message=f"found environment value for {label}",
            details={"names": list(names)},
        )

    return CheckResult(
        name=f"env:{label}",
        status="error" if required else "warn",
        message=f"missing environment value for {label}",
        details={"expected_any_of": list(names)},
    )


def run_checks(
    *,
    root: Path | None,
    require_gateway: bool,
    require_skillgrade: bool,
    require_gitlab: bool,
) -> list[CheckResult]:
    """Run the doctor checks and return the outcomes."""
    load_env_file(root)
    results = [
        check_repo_root(root),
        check_env_file(root),
        check_import_resolution(root),
        check_command("python", required=True),
        check_command("pytest", required=False),
        check_command("ruff", required=False),
    ]

    if require_gateway:
        results.extend(
            [
                check_env_group("api-key", ("API_KEY", "NVIDIA_API_KEY"), required=True),
                check_env_group(
                    "gateway-url",
                    ("GATEWAY_URL", "NVIDIA_GATEWAY_URL"),
                    required=True,
                ),
            ]
        )
    else:
        results.extend(
            [
                check_env_group("api-key", ("API_KEY", "NVIDIA_API_KEY"), required=False),
                check_env_group(
                    "gateway-url",
                    ("GATEWAY_URL", "NVIDIA_GATEWAY_URL"),
                    required=False,
                ),
            ]
        )

    results.append(check_command("skillgrade", required=require_skillgrade))
    results.append(check_command("glab", required=require_gitlab))
    if require_gitlab:
        results.append(
            check_env_group(
                "gitlab-pat",
                ("GITLAB_PERSONAL_ACCESS_TOKEN",),
                required=True,
            )
        )
    else:
        results.append(
            check_env_group(
                "gitlab-pat",
                ("GITLAB_PERSONAL_ACCESS_TOKEN",),
                required=False,
            )
        )

    return results


def build_payload(root: Path | None, checks: list[CheckResult]) -> dict[str, object]:
    errors = sum(1 for check in checks if check.status == "error")
    warnings = sum(1 for check in checks if check.status == "warn")
    return {
        "root": str(root) if root is not None else None,
        "summary": {
            "checks": len(checks),
            "errors": errors,
            "warnings": warnings,
        },
        "checks": [asdict(check) for check in checks],
    }


def print_text(payload: dict[str, object]) -> None:
    summary = payload["summary"]
    print(
        "summary:"
        f" checks={summary['checks']}"
        f" errors={summary['errors']}"
        f" warnings={summary['warnings']}"
    )
    for check in payload["checks"]:
        print(f"{check['status']}\t{check['name']}\t{check['message']}")


def cmd_check(args: argparse.Namespace) -> int:
    root = find_repo_root(args.root)
    checks = run_checks(
        root=root,
        require_gateway=args.require_gateway,
        require_skillgrade=args.require_skillgrade,
        require_gitlab=args.require_gitlab,
    )
    payload = build_payload(root, checks)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print_text(payload)
    return 1 if payload["summary"]["errors"] else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="Run Pantheon environment and workspace diagnostics")
    check.add_argument("--root", help="Override the repository root instead of discovering it")
    check.add_argument("--json", action="store_true", help="Emit JSON instead of text output")
    check.add_argument(
        "--require-gateway",
        action="store_true",
        help="Treat missing API_KEY/GATEWAY_URL configuration as an error",
    )
    check.add_argument(
        "--require-skillgrade",
        action="store_true",
        help="Treat a missing skillgrade installation as an error",
    )
    check.add_argument(
        "--require-gitlab",
        action="store_true",
        help="Treat missing GitLab CLI/PAT configuration as an error",
    )
    check.set_defaults(func=cmd_check)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
