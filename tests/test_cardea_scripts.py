"""Tests for Cardea and shared safety utility scripts."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
OVERLAY_GUARD_PATH = REPO_ROOT / ".agents" / "scripts" / "overlay_guard.py"
GITLAB_OPS_PATH = (
    REPO_ROOT / ".agents" / "skills" / "cardea" / "scripts" / "gitlab_ops.py"
)


def load_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


overlay_guard = load_module("test_overlay_guard", OVERLAY_GUARD_PATH)
gitlab_ops = load_module("test_gitlab_ops", GITLAB_OPS_PATH)


class FakeGitLabClient:
    def __init__(
        self,
        *,
        projects: dict[str, dict] | None = None,
        branches: dict[tuple[str, str], dict] | None = None,
        files: dict[tuple[str, str, str], dict] | None = None,
        namespaces: dict[str, dict] | None = None,
    ):
        self.projects = projects or {}
        self.branches = branches or {}
        self.files = files or {}
        self.namespaces = namespaces or {}
        self.last_create_payload: dict | None = None

    def project(self, project_path: str):
        return self.projects.get(project_path)

    def branch(self, project_path: str, branch_name: str):
        return self.branches.get((project_path, branch_name))

    def file(self, project_path: str, file_path: str, ref: str):
        return self.files.get((project_path, file_path, ref))

    def namespace(self, namespace_ref: str):
        return self.namespaces[namespace_ref]

    def create_project(self, payload: dict):
        self.last_create_payload = payload
        return {
            "id": 42,
            "name": payload["name"],
            "path": payload["path"],
            "path_with_namespace": f"team/{payload['path']}",
            "default_branch": payload.get("default_branch"),
            "web_url": f"https://gitlab.example.com/team/{payload['path']}",
        }


class TestOverlayGuard:
    def test_build_plan_classifies_paths(self, tmp_path):
        source = tmp_path / "source"
        target = tmp_path / "target"
        source.mkdir()
        target.mkdir()

        (source / "missing.txt").write_text("missing", encoding="utf-8")
        (source / "same.txt").write_text("same", encoding="utf-8")
        (target / "same.txt").write_text("same", encoding="utf-8")
        (source / "conflict.txt").write_text("source", encoding="utf-8")
        (target / "conflict.txt").write_text("target", encoding="utf-8")

        decisions = overlay_guard.build_plan(source, target)
        by_path = {item.path: item for item in decisions}

        assert by_path["missing.txt"].action == "create-safe"
        assert by_path["same.txt"].action == "identical"
        assert by_path["conflict.txt"].action == "review-required"

    def test_copy_missing_only_copies_absent_targets(self, tmp_path):
        source = tmp_path / "source"
        target = tmp_path / "target"
        source.mkdir()
        target.mkdir()

        (source / "configs").mkdir()
        (source / "configs" / "new.yml").write_text("new", encoding="utf-8")
        (source / "configs" / "existing.yml").write_text("source", encoding="utf-8")
        (target / "configs").mkdir()
        (target / "configs" / "existing.yml").write_text("target", encoding="utf-8")

        decisions = overlay_guard.build_plan(source, target)
        copied = overlay_guard.copy_create_safe_files(source, target, decisions)

        assert copied == ["configs/new.yml"]
        assert (target / "configs" / "new.yml").read_text(encoding="utf-8") == "new"
        assert (
            target / "configs" / "existing.yml"
        ).read_text(encoding="utf-8") == "target"

    def test_render_review_markdown_lists_conflicts(self, tmp_path):
        source = tmp_path / "source"
        target = tmp_path / "target"
        source.mkdir()
        target.mkdir()

        (source / "conflict.txt").write_text("source", encoding="utf-8")
        (target / "conflict.txt").write_text("target", encoding="utf-8")

        decisions = overlay_guard.build_plan(source, target)
        rendered = overlay_guard.render_review_markdown(source, target, decisions)

        assert "# Overlay Review Package" in rendered
        assert "`conflict.txt`: target file already exists with different content" in rendered


class TestGitLabOps:
    def test_split_project_path_requires_namespace(self):
        with pytest.raises(SystemExit, match="namespace and project name"):
            gitlab_ops.split_project_path("repo-only")

    def test_check_project_blocks_existing_targets(self):
        client = FakeGitLabClient(
            projects={
                "group/existing": {
                    "id": 9,
                    "name": "existing",
                    "path": "existing",
                    "path_with_namespace": "group/existing",
                    "default_branch": "main",
                    "web_url": "https://gitlab.example.com/group/existing",
                }
            }
        )

        result = gitlab_ops.check_project(client, "group/existing")

        assert result.classification == "review-required"
        assert result.exists is True
        assert result.details["path_with_namespace"] == "group/existing"

    def test_check_file_marks_absent_target_create_safe(self):
        client = FakeGitLabClient()

        result = gitlab_ops.check_file(client, "group/repo", "ci/config.yml", "main")

        assert result.classification == "create-safe"
        assert result.exists is False

    def test_create_project_plan_blocks_existing_project(self):
        client = FakeGitLabClient(
            projects={
                "group/existing": {
                    "id": 9,
                    "name": "existing",
                    "path": "existing",
                    "path_with_namespace": "group/existing",
                    "default_branch": "main",
                    "web_url": "https://gitlab.example.com/group/existing",
                }
            }
        )

        payload = gitlab_ops.create_project_plan(client, "group/existing")

        assert payload["status"] == "blocked"
        assert payload["classification"] == "review-required"
        assert payload["existing_project"]["path_with_namespace"] == "group/existing"

    def test_create_project_plan_dry_run_resolves_namespace(self):
        client = FakeGitLabClient(
            namespaces={
                "group": {
                    "id": 101,
                    "full_path": "group",
                    "kind": "group",
                }
            }
        )

        payload = gitlab_ops.create_project_plan(
            client,
            "group/new-repo",
            default_branch="main",
            initialize_with_readme=True,
            dry_run=True,
        )

        assert payload["status"] == "dry-run"
        assert payload["classification"] == "create-safe"
        assert payload["planned_payload"]["namespace_id"] == 101
        assert payload["planned_payload"]["path"] == "new-repo"
        assert payload["planned_payload"]["initialize_with_readme"] is True

    def test_create_project_plan_creates_project_when_safe(self):
        client = FakeGitLabClient(
            namespaces={
                "team": {
                    "id": 7,
                    "full_path": "team",
                    "kind": "group",
                }
            }
        )

        payload = gitlab_ops.create_project_plan(
            client,
            "team/new-service",
            name="New Service",
            visibility="internal",
        )

        assert payload["status"] == "created"
        assert payload["project"]["path_with_namespace"] == "team/new-service"
        assert client.last_create_payload == {
            "namespace_id": 7,
            "path": "new-service",
            "name": "New Service",
            "visibility": "internal",
        }
