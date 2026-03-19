"""Tests for shared utility scripts."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[1]
DOCTOR_PATH = REPO_ROOT / ".agents" / "scripts" / "doctor.py"
SECRET_SCAN_PATH = REPO_ROOT / ".agents" / "scripts" / "secret_scan.py"


def load_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


doctor = load_module("test_doctor_module", DOCTOR_PATH)
secret_scan = load_module("test_secret_scan_module", SECRET_SCAN_PATH)


def write(path: Path, content: str, *, binary: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if binary:
        path.write_bytes(content.encode("utf-8"))
    else:
        path.write_text(content, encoding="utf-8")


class TestDoctor:
    def test_find_repo_root_from_nested_directory(self, tmp_path):
        repo = tmp_path / "repo"
        (repo / ".agents" / "skills").mkdir(parents=True)
        write(repo / "pyproject.toml", "[project]\nname='pantheon'\nversion='0.1.0'\n")
        nested = repo / "nested" / "dir"
        nested.mkdir(parents=True)

        assert doctor.find_repo_root(nested) == repo

    def test_check_import_resolution_warns_for_other_checkout(self, tmp_path, monkeypatch):
        repo = tmp_path / "repo"
        (repo / ".agents" / "skills").mkdir(parents=True)
        write(repo / "pyproject.toml", "[project]\nname='pantheon'\nversion='0.1.0'\n")

        fake_spec = SimpleNamespace(
            origin=str(tmp_path / "other" / "src" / "pantheon" / "__init__.py"),
            submodule_search_locations=None,
        )
        monkeypatch.setattr(doctor.importlib.util, "find_spec", lambda _name: fake_spec)

        result = doctor.check_import_resolution(repo)

        assert result.status == "warn"
        assert "different location" in result.message

    def test_run_checks_requires_gateway_env_when_requested(self, tmp_path, monkeypatch):
        repo = tmp_path / "repo"
        (repo / ".agents" / "skills").mkdir(parents=True)
        write(repo / "pyproject.toml", "[project]\nname='pantheon'\nversion='0.1.0'\n")
        monkeypatch.delenv("API_KEY", raising=False)
        monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
        monkeypatch.delenv("GATEWAY_URL", raising=False)
        monkeypatch.delenv("NVIDIA_GATEWAY_URL", raising=False)
        monkeypatch.setattr(doctor.shutil, "which", lambda name: f"/usr/bin/{name}")
        monkeypatch.setattr(
            doctor.importlib.util,
            "find_spec",
            lambda _name: SimpleNamespace(
                origin=str(repo / "src" / "pantheon" / "__init__.py"),
                submodule_search_locations=None,
            ),
        )

        checks = doctor.run_checks(
            root=repo,
            require_gateway=True,
            require_skillgrade=False,
            require_gitlab=False,
        )

        failing = [check for check in checks if check.status == "error"]
        assert any(check.name == "env:api-key" for check in failing)
        assert any(check.name == "env:gateway-url" for check in failing)

    def test_run_checks_loads_env_file_before_env_validation(self, tmp_path, monkeypatch):
        repo = tmp_path / "repo"
        (repo / ".agents" / "skills").mkdir(parents=True)
        write(repo / "pyproject.toml", "[project]\nname='pantheon'\nversion='0.1.0'\n")
        write(
            repo / ".env",
            "API_KEY=from-env-file\nGATEWAY_URL=https://gateway.example/v1\n"
            "GITLAB_PERSONAL_ACCESS_TOKEN=gitlab-token\n",
        )
        monkeypatch.delenv("API_KEY", raising=False)
        monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
        monkeypatch.delenv("GATEWAY_URL", raising=False)
        monkeypatch.delenv("NVIDIA_GATEWAY_URL", raising=False)
        monkeypatch.delenv("GITLAB_PERSONAL_ACCESS_TOKEN", raising=False)
        monkeypatch.setattr(doctor.shutil, "which", lambda name: f"/usr/bin/{name}")
        monkeypatch.setattr(
            doctor.importlib.util,
            "find_spec",
            lambda _name: SimpleNamespace(
                origin=str(repo / "src" / "pantheon" / "__init__.py"),
                submodule_search_locations=None,
            ),
        )

        checks = doctor.run_checks(
            root=repo,
            require_gateway=True,
            require_skillgrade=False,
            require_gitlab=True,
        )

        by_name = {check.name: check for check in checks}
        assert by_name["env:api-key"].status == "ok"
        assert by_name["env:gateway-url"].status == "ok"
        assert by_name["env:gitlab-pat"].status == "ok"


class TestSecretScan:
    def test_scan_path_finds_secret_and_eval(self, tmp_path):
        root = tmp_path / "repo"
        write(root / "app.py", 'API_KEY = "super-secret"\nvalue = eval(user_input)\n')

        findings = secret_scan.scan_path(root)
        rule_ids = {finding.rule_id for finding in findings}

        assert "secret-assignment" in rule_ids
        assert "dangerous-eval" in rule_ids
        previews = {finding.rule_id: finding.preview for finding in findings}
        assert previews["secret-assignment"].endswith("[redacted]")

    def test_scan_path_respects_excludes(self, tmp_path):
        root = tmp_path / "repo"
        write(root / "ignored" / "secret.txt", 'token = "ignore-me"\n')

        findings = secret_scan.scan_path(root, exclude_patterns=["ignored/*"])

        assert findings == []

    def test_scan_path_skips_binary_files(self, tmp_path):
        root = tmp_path / "repo"
        binary_file = root / "blob.bin"
        binary_file.parent.mkdir(parents=True, exist_ok=True)
        binary_file.write_bytes(b"\x00\x01\x02secret")

        findings = secret_scan.scan_path(root)

        assert findings == []
