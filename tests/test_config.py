"""Tests for configuration — env loading, directory discovery, defaults."""

import os
from unittest.mock import patch

from pantheon.config import (
    api_key,
    gateway_url,
    load_env,
    memory_dir,
    repo_root,
    skills_dir,
    verbose,
)


class TestLoadEnv:
    def test_loads_from_file(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("TEST_PANTHEON_VAR=hello\n")

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TEST_PANTHEON_VAR", None)
            load_env(str(env_file))
            assert os.environ["TEST_PANTHEON_VAR"] == "hello"
            del os.environ["TEST_PANTHEON_VAR"]

    def test_skips_comments_and_blanks(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("# comment\n\nTEST_PANTHEON_VAR2=world\n")

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TEST_PANTHEON_VAR2", None)
            load_env(str(env_file))
            assert os.environ["TEST_PANTHEON_VAR2"] == "world"
            del os.environ["TEST_PANTHEON_VAR2"]

    def test_does_not_override_existing(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("TEST_PANTHEON_VAR3=new\n")

        with patch.dict(os.environ, {"TEST_PANTHEON_VAR3": "existing"}, clear=False):
            load_env(str(env_file))
            assert os.environ["TEST_PANTHEON_VAR3"] == "existing"

    def test_missing_file_is_noop(self):
        load_env("/nonexistent/.env")

    def test_strips_double_quotes(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text('TEST_PANTHEON_QUOTED="hello world"\n')

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TEST_PANTHEON_QUOTED", None)
            load_env(str(env_file))
            assert os.environ["TEST_PANTHEON_QUOTED"] == "hello world"
            del os.environ["TEST_PANTHEON_QUOTED"]

    def test_strips_single_quotes(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("TEST_PANTHEON_SQ='single'\n")

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TEST_PANTHEON_SQ", None)
            load_env(str(env_file))
            assert os.environ["TEST_PANTHEON_SQ"] == "single"
            del os.environ["TEST_PANTHEON_SQ"]

    def test_handles_values_with_equals(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("TEST_PANTHEON_URL=http://host?a=1&b=2\n")

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TEST_PANTHEON_URL", None)
            load_env(str(env_file))
            assert os.environ["TEST_PANTHEON_URL"] == "http://host?a=1&b=2"
            del os.environ["TEST_PANTHEON_URL"]

    def test_default_env_resolves_repo_root(self, tmp_path, monkeypatch):
        repo = tmp_path / "repo"
        env_file = repo / ".env"
        env_file.parent.mkdir(parents=True)
        env_file.write_text("TEST_PANTHEON_ROOTED=repo-root\n")
        (repo / ".agents" / "skills").mkdir(parents=True)
        (repo / "pyproject.toml").write_text("[project]\nname='pantheon'\nversion='0.1.0'\n")
        workdir = repo / "nested" / "dir"
        workdir.mkdir(parents=True)
        monkeypatch.chdir(workdir)

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TEST_PANTHEON_ROOTED", None)
            load_env()
            assert os.environ["TEST_PANTHEON_ROOTED"] == "repo-root"
            del os.environ["TEST_PANTHEON_ROOTED"]

    def test_explicit_relative_env_stays_relative_to_cwd(self, tmp_path, monkeypatch):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".agents" / "skills").mkdir(parents=True)
        (repo / "pyproject.toml").write_text("[project]\nname='pantheon'\nversion='0.1.0'\n")
        workdir = repo / "nested"
        workdir.mkdir()
        env_file = workdir / "custom.env"
        env_file.write_text("TEST_PANTHEON_CUSTOM=custom\n")
        monkeypatch.chdir(workdir)

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TEST_PANTHEON_CUSTOM", None)
            load_env("custom.env")
            assert os.environ["TEST_PANTHEON_CUSTOM"] == "custom"
            del os.environ["TEST_PANTHEON_CUSTOM"]


class TestSkillsDir:
    def test_env_override(self):
        with patch.dict(os.environ, {"SKILLS_DIR": "/custom/skills"}):
            assert skills_dir() == "/custom/skills"

    def test_agents_dir_fallback(self):
        with patch.dict(os.environ, {"AGENTS_DIR": "/agents"}, clear=False):
            os.environ.pop("SKILLS_DIR", None)
            assert skills_dir() == "/agents"

    def test_default_when_no_env(self, tmp_path, monkeypatch):
        monkeypatch.delenv("SKILLS_DIR", raising=False)
        monkeypatch.delenv("AGENTS_DIR", raising=False)
        monkeypatch.chdir(tmp_path)
        assert skills_dir() == ".agents/skills"


class TestRepoRoot:
    def test_repo_root_found_from_nested_directory(self, tmp_path):
        repo = tmp_path / "repo"
        (repo / ".agents" / "skills").mkdir(parents=True)
        (repo / "pyproject.toml").write_text("[project]\nname='pantheon'\nversion='0.1.0'\n")
        nested = repo / "a" / "b"
        nested.mkdir(parents=True)

        assert repo_root(nested) == repo

    def test_repo_root_returns_none_when_not_found(self, tmp_path):
        outside = tmp_path / "outside"
        outside.mkdir()

        assert repo_root(outside) is None


class TestGatewayUrl:
    def test_env_override(self):
        with patch.dict(os.environ, {"GATEWAY_URL": "http://custom/v1/"}):
            assert gateway_url() == "http://custom/v1"

    def test_nvidia_fallback(self):
        with patch.dict(os.environ, {"NVIDIA_GATEWAY_URL": "http://nvidia/v1"}, clear=False):
            os.environ.pop("GATEWAY_URL", None)
            result = gateway_url()
            assert result == "http://nvidia/v1"

    def test_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GATEWAY_URL", None)
            os.environ.pop("NVIDIA_GATEWAY_URL", None)
            assert "nvidia" in gateway_url()


class TestApiKey:
    def test_env_override(self):
        with patch.dict(os.environ, {"API_KEY": "secret"}):
            assert api_key() == "secret"

    def test_nvidia_fallback(self):
        with patch.dict(os.environ, {"NVIDIA_API_KEY": "nv-key"}, clear=False):
            os.environ.pop("API_KEY", None)
            assert api_key() == "nv-key"

    def test_default_empty(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("API_KEY", None)
            os.environ.pop("NVIDIA_API_KEY", None)
            assert api_key() == ""


class TestMemoryDir:
    def test_env_override(self):
        with patch.dict(os.environ, {"MEMORY_DIR": "/custom/mem"}):
            assert memory_dir() == "/custom/mem"

    def test_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MEMORY_DIR", None)
            assert memory_dir() == ".memory"


class TestVerbose:
    def test_true_values(self):
        with patch.dict(os.environ, {"VERBOSE": "1"}):
            assert verbose() is True
        with patch.dict(os.environ, {"VERBOSE": "true"}):
            assert verbose() is True

    def test_false_values(self):
        with patch.dict(os.environ, {"VERBOSE": ""}):
            assert verbose() is False
        with patch.dict(os.environ, {"VERBOSE": "0"}):
            assert verbose() is False

    def test_unset(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("VERBOSE", None)
            assert verbose() is False
