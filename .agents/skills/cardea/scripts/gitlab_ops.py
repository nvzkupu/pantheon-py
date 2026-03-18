#!/usr/bin/env python3
"""Safe GitLab helpers for Cardea and other Pantheon members."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

TOKEN_ENV = "GITLAB_PERSONAL_ACCESS_TOKEN"
BASE_URL_ENV = "GITLAB_API_BASE_URL"


def find_repo_root(start: Path | None = None) -> Path:
    """Walk upward until the repository root is found."""
    current = (start or Path(__file__)).resolve()
    if current.is_file():
        current = current.parent

    for candidate in (current, *current.parents):
        if (candidate / "pyproject.toml").exists() and (candidate / ".agents" / "skills").is_dir():
            return candidate
    raise SystemExit("Could not determine repository root for gitlab_ops.py")


REPO_ROOT = find_repo_root()
ENV_PATH = REPO_ROOT / ".env"


class GitLabApiError(RuntimeError):
    """Structured API failure with status code and response body."""

    def __init__(self, status_code: int, body: str):
        super().__init__(f"GitLab API error {status_code}: {body}")
        self.status_code = status_code
        self.body = body


@dataclass(frozen=True)
class GateResult:
    target_type: str
    target: str
    exists: bool
    classification: str
    reason: str
    next_step: str
    details: dict[str, Any] | None = None


def load_env() -> None:
    if not ENV_PATH.exists():
        return

    for raw_line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key in {TOKEN_ENV, BASE_URL_ENV} and key not in os.environ:
            os.environ[key] = value


def api_token(required: bool = True) -> str:
    load_env()
    token = os.environ.get(TOKEN_ENV, "").strip()
    if token or not required:
        return token
    raise SystemExit(f"Missing {TOKEN_ENV} in environment")


def git_remote_url() -> str:
    result = subprocess.run(
        ["git", "config", "--get", "remote.origin.url"],
        capture_output=True,
        text=True,
        check=False,
    )
    remote = result.stdout.strip()
    if remote:
        return remote
    raise SystemExit("Could not determine git remote origin URL")


def api_base_url(explicit: str | None = None) -> str:
    load_env()
    if explicit:
        return explicit.rstrip("/")

    override = os.environ.get(BASE_URL_ENV, "").strip()
    if override:
        return override.rstrip("/")

    remote_url = git_remote_url()
    if remote_url.startswith("git@"):
        host = remote_url.split("@", 1)[1].split(":", 1)[0]
        return f"https://{host}/api/v4"

    parsed = urllib.parse.urlparse(remote_url)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}/api/v4"

    raise SystemExit(
        f"Could not derive {BASE_URL_ENV} from git remote origin: {remote_url}"
    )


def encoded_path(path: str) -> str:
    return urllib.parse.quote(path.strip("/"), safe="")


def split_project_path(project_path: str) -> tuple[str, str]:
    parts = [part for part in project_path.strip("/").split("/") if part]
    if len(parts) < 2:
        raise SystemExit(
            "Project path must include a namespace and project name, like group/repo"
        )
    return "/".join(parts[:-1]), parts[-1]


def narrow_project(project: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": project.get("id"),
        "name": project.get("name"),
        "path": project.get("path"),
        "path_with_namespace": project.get("path_with_namespace"),
        "default_branch": project.get("default_branch"),
        "web_url": project.get("web_url"),
    }


class GitLabClient:
    """Thin GitLab API wrapper built on urllib for portability."""

    def __init__(self, base_url: str, token: str):
        self.base_url = base_url.rstrip("/")
        self.token = token

    def request_json(
        self,
        method: str,
        endpoint: str,
        *,
        query: dict[str, str] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        if query:
            url = f"{url}?{urllib.parse.urlencode(query)}"

        body: bytes | None = None
        headers = {"PRIVATE-TOKEN": self.token}
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                data = response.read()
        except urllib.error.HTTPError as exc:
            body_text = exc.read().decode("utf-8", "replace")
            raise GitLabApiError(exc.code, body_text) from None
        except urllib.error.URLError as exc:
            raise SystemExit(f"GitLab API request failed: {exc}") from None

        if not data:
            return {}
        return json.loads(data.decode("utf-8"))

    def project(self, project_path: str) -> dict[str, Any] | None:
        try:
            return self.request_json("GET", f"projects/{encoded_path(project_path)}")
        except GitLabApiError as exc:
            if exc.status_code == 404:
                return None
            raise

    def branch(self, project_path: str, branch_name: str) -> dict[str, Any] | None:
        endpoint = (
            f"projects/{encoded_path(project_path)}/repository/branches/"
            f"{encoded_path(branch_name)}"
        )
        try:
            return self.request_json("GET", endpoint)
        except GitLabApiError as exc:
            if exc.status_code == 404:
                return None
            raise

    def file(self, project_path: str, file_path: str, ref: str) -> dict[str, Any] | None:
        endpoint = (
            f"projects/{encoded_path(project_path)}/repository/files/"
            f"{encoded_path(file_path.lstrip('/'))}"
        )
        try:
            return self.request_json("GET", endpoint, query={"ref": ref})
        except GitLabApiError as exc:
            if exc.status_code == 404:
                return None
            raise

    def namespace(self, namespace_ref: str) -> dict[str, Any]:
        if namespace_ref.isdigit():
            return self.request_json("GET", f"namespaces/{namespace_ref}")

        try:
            return self.request_json("GET", f"namespaces/{encoded_path(namespace_ref)}")
        except GitLabApiError as exc:
            if exc.status_code != 404:
                raise

        search_term = namespace_ref.strip("/").split("/")[-1]
        candidates = self.request_json(
            "GET",
            "namespaces",
            query={"search": search_term, "per_page": "100"},
        )
        matches = [
            item
            for item in candidates
            if item.get("full_path") == namespace_ref or item.get("path") == namespace_ref
        ]
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise SystemExit(f"Could not resolve namespace: {namespace_ref}")
        raise SystemExit(f"Namespace lookup is ambiguous: {namespace_ref}")

    def create_project(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.request_json("POST", "projects", payload=payload)

    def user(self) -> dict[str, Any]:
        return self.request_json("GET", "user")


def gate_for(
    *,
    target_type: str,
    target: str,
    exists: bool,
    reason_if_exists: str,
    reason_if_absent: str,
    details: dict[str, Any] | None = None,
) -> GateResult:
    if exists:
        return GateResult(
            target_type=target_type,
            target=target,
            exists=True,
            classification="review-required",
            reason=reason_if_exists,
            next_step="Prepare a review package before publishing any change.",
            details=details,
        )

    return GateResult(
        target_type=target_type,
        target=target,
        exists=False,
        classification="create-safe",
        reason=reason_if_absent,
        next_step="Safe to create because the target does not exist yet.",
        details=details,
    )


def check_project(client: GitLabClient, project_path: str) -> GateResult:
    project = client.project(project_path)
    return gate_for(
        target_type="project",
        target=project_path,
        exists=project is not None,
        reason_if_exists="project path already exists in GitLab",
        reason_if_absent="project path is available for creation",
        details=narrow_project(project) if project else None,
    )


def check_branch(client: GitLabClient, project_path: str, branch_name: str) -> GateResult:
    branch = client.branch(project_path, branch_name)
    details = None
    if branch:
        details = {
            "name": branch.get("name"),
            "default": branch.get("default"),
            "protected": branch.get("protected"),
            "merged": branch.get("merged"),
            "web_url": branch.get("web_url"),
        }
    return gate_for(
        target_type="branch",
        target=f"{project_path}:{branch_name}",
        exists=branch is not None,
        reason_if_exists="branch already exists in the target project",
        reason_if_absent="branch name is available for creation",
        details=details,
    )


def check_file(
    client: GitLabClient,
    project_path: str,
    file_path: str,
    ref: str,
) -> GateResult:
    file_info = client.file(project_path, file_path, ref)
    details = None
    if file_info:
        details = {
            "file_path": file_info.get("file_path"),
            "ref": ref,
            "blob_id": file_info.get("blob_id"),
            "commit_id": file_info.get("commit_id"),
        }
    return gate_for(
        target_type="file",
        target=f"{project_path}:{ref}:{file_path}",
        exists=file_info is not None,
        reason_if_exists="file path already exists at the requested ref",
        reason_if_absent="file path is absent at the requested ref",
        details=details,
    )


def create_project_plan(
    client: GitLabClient,
    project_path: str,
    *,
    name: str | None = None,
    description: str | None = None,
    visibility: str = "private",
    default_branch: str | None = None,
    initialize_with_readme: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    gate = check_project(client, project_path)
    if gate.exists:
        return {
            "status": "blocked",
            "classification": gate.classification,
            "reason": gate.reason,
            "next_step": gate.next_step,
            "project_path": project_path,
            "existing_project": gate.details,
        }

    namespace_path, repo_path = split_project_path(project_path)
    namespace = client.namespace(namespace_path)
    payload: dict[str, Any] = {
        "namespace_id": namespace["id"],
        "path": repo_path,
        "name": name or repo_path,
        "visibility": visibility,
    }
    if description:
        payload["description"] = description
    if default_branch:
        payload["default_branch"] = default_branch
    if initialize_with_readme:
        payload["initialize_with_readme"] = True

    result: dict[str, Any] = {
        "status": "dry-run" if dry_run else "ready",
        "classification": "create-safe",
        "reason": "project path is absent and safe to create",
        "project_path": project_path,
        "namespace": {
            "id": namespace.get("id"),
            "full_path": namespace.get("full_path"),
            "kind": namespace.get("kind"),
        },
        "planned_payload": payload,
    }
    if dry_run:
        return result

    created = client.create_project(payload)
    result["status"] = "created"
    result["project"] = narrow_project(created)
    return result


def gate_payload(result: GateResult) -> dict[str, Any]:
    payload = asdict(result)
    if payload["details"] is None:
        payload.pop("details")
    return payload


def print_gate(result: GateResult, json_mode: bool) -> None:
    payload = gate_payload(result)
    if json_mode:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return

    print(
        f"{result.classification}\t{result.target_type}\t{result.target}\t{result.reason}"
    )
    print(f"next-step\t{result.next_step}")
    if result.details:
        print(json.dumps(result.details, indent=2, sort_keys=True))


def print_payload(payload: dict[str, Any], json_mode: bool) -> None:
    if json_mode:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return

    print(
        f"{payload.get('classification', 'info')}\t"
        f"{payload.get('status', 'status')}\t"
        f"{payload.get('project_path', payload.get('api_base_url', 'n/a'))}\t"
        f"{payload.get('reason', 'ok')}"
    )
    if payload.get("next_step"):
        print(f"next-step\t{payload['next_step']}")
    if payload.get("project"):
        print(json.dumps(payload["project"], indent=2, sort_keys=True))
    elif payload.get("existing_project"):
        print(json.dumps(payload["existing_project"], indent=2, sort_keys=True))
    elif payload.get("user"):
        print(json.dumps(payload["user"], indent=2, sort_keys=True))
    if payload.get("planned_payload"):
        print("planned-payload")
        print(json.dumps(payload["planned_payload"], indent=2, sort_keys=True))


def build_client(args: argparse.Namespace) -> GitLabClient:
    return GitLabClient(api_base_url(args.api_base), api_token())


def cmd_auth_status(args: argparse.Namespace) -> int:
    load_env()
    payload: dict[str, Any] = {
        "token_present": bool(api_token(required=False)),
        "api_base_url": api_base_url(args.api_base),
    }
    if args.check_api:
        client = GitLabClient(payload["api_base_url"], api_token())
        user = client.user()
        payload["user"] = {
            "id": user.get("id"),
            "username": user.get("username"),
            "name": user.get("name"),
            "web_url": user.get("web_url"),
        }
    print_payload(payload, args.json)
    return 0


def cmd_project_check(args: argparse.Namespace) -> int:
    print_gate(check_project(build_client(args), args.project_path), args.json)
    return 0


def cmd_branch_check(args: argparse.Namespace) -> int:
    print_gate(
        check_branch(build_client(args), args.project_path, args.branch_name),
        args.json,
    )
    return 0


def cmd_file_check(args: argparse.Namespace) -> int:
    print_gate(
        check_file(build_client(args), args.project_path, args.file_path, args.ref),
        args.json,
    )
    return 0


def cmd_create_project(args: argparse.Namespace) -> int:
    payload = create_project_plan(
        build_client(args),
        args.project_path,
        name=args.name,
        description=args.description,
        visibility=args.visibility,
        default_branch=args.default_branch,
        initialize_with_readme=args.initialize_with_readme,
        dry_run=args.dry_run,
    )
    print_payload(payload, args.json)
    return 2 if payload["status"] == "blocked" else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--api-base",
        help=f"Override {BASE_URL_ENV} instead of deriving it from the git remote",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON to stdout where applicable",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    auth = sub.add_parser("auth-status", help="Report auth and API base configuration")
    auth.add_argument(
        "--check-api",
        action="store_true",
        help="Call /user to confirm the token is usable",
    )
    auth.set_defaults(func=cmd_auth_status)

    project_check = sub.add_parser(
        "project-check",
        help="Check whether a project path already exists",
    )
    project_check.add_argument("project_path", help="Project path like group/repo")
    project_check.set_defaults(func=cmd_project_check)

    branch_check = sub.add_parser(
        "branch-check",
        help="Check whether a branch already exists in a project",
    )
    branch_check.add_argument("project_path", help="Project path like group/repo")
    branch_check.add_argument("branch_name", help="Branch name to inspect")
    branch_check.set_defaults(func=cmd_branch_check)

    file_check = sub.add_parser(
        "file-check",
        help="Check whether a file path exists at a given ref",
    )
    file_check.add_argument("project_path", help="Project path like group/repo")
    file_check.add_argument("file_path", help="Repository-relative file path")
    file_check.add_argument(
        "--ref",
        default="HEAD",
        help="Branch, tag, or commit to inspect",
    )
    file_check.set_defaults(func=cmd_file_check)

    create = sub.add_parser(
        "create-project",
        help="Create a new GitLab project only when the path is absent",
    )
    create.add_argument("project_path", help="Target project path like group/repo")
    create.add_argument("--name", help="Display name for the project")
    create.add_argument("--description", help="Project description")
    create.add_argument(
        "--visibility",
        choices=["private", "internal", "public"],
        default="private",
        help="GitLab visibility for the new project",
    )
    create.add_argument(
        "--default-branch",
        help="Default branch name for the new project",
    )
    create.add_argument(
        "--initialize-with-readme",
        action="store_true",
        help="Ask GitLab to initialize the repository with a README",
    )
    create.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve the namespace and show the create payload without creating anything",
    )
    create.set_defaults(func=cmd_create_project)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return args.func(args)
    except GitLabApiError as exc:
        raise SystemExit(str(exc)) from None


if __name__ == "__main__":
    raise SystemExit(main())
