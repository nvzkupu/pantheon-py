"""Tests for tool interface, registry, validation, and builtins."""

import tempfile
from pathlib import Path

from pantheon.tools import (
    Registry, Tool, check_required, strict_schema, builtins,
    ReadFile, WriteFile, ListDir,
)


class EchoTool(Tool):
    def name(self) -> str:
        return "echo"

    def description(self) -> str:
        return "Echo back the message."

    def parameters(self) -> dict:
        return strict_schema(
            {"msg": {"type": "string", "description": "Message"}},
            ["msg"],
        )

    def execute(self, args: dict) -> str:
        return args["msg"]


class TestRegistry:
    def test_register_and_get(self):
        r = Registry()
        r.register(EchoTool())
        tool = r.get("echo")
        assert tool is not None
        assert tool.name() == "echo"

    def test_get_missing(self):
        r = Registry()
        assert r.get("nope") is None

    def test_definitions(self):
        r = Registry()
        r.register(EchoTool())
        defs = r.definitions()
        assert len(defs) == 1
        assert defs[0]["type"] == "function"
        assert defs[0]["function"]["strict"] is True
        assert defs[0]["function"]["parameters"]["additionalProperties"] is False

    def test_execute_success(self):
        r = Registry()
        r.register(EchoTool())
        result = r.execute("echo", '{"msg": "hello"}')
        assert result == "hello"

    def test_execute_unknown(self):
        r = Registry()
        result = r.execute("nope", "{}")
        assert "unknown tool" in result

    def test_execute_missing_required(self):
        r = Registry()
        r.register(EchoTool())
        result = r.execute("echo", "{}")
        assert "missing required" in result

    def test_execute_all(self):
        r = Registry()
        r.register(EchoTool())
        calls = [
            {"id": "c1", "function": {"name": "echo", "arguments": '{"msg": "a"}'}},
            {"id": "c2", "function": {"name": "echo", "arguments": '{"msg": "b"}'}},
        ]
        results = r.execute_all(calls)
        assert len(results) == 2
        assert results[0]["content"] == "a"
        assert results[1]["content"] == "b"
        assert results[0]["role"] == "tool"
        assert results[0]["tool_call_id"] == "c1"


class TestCheckRequired:
    def test_all_present(self):
        schema = {"required": ["a", "b"]}
        assert check_required(schema, {"a": 1, "b": 2}) == []

    def test_missing(self):
        schema = {"required": ["a", "b"]}
        assert check_required(schema, {"a": 1}) == ["b"]

    def test_null_value(self):
        schema = {"required": ["a"]}
        assert check_required(schema, {"a": None}) == ["a"]

    def test_no_required(self):
        assert check_required({}, {"anything": True}) == []


class TestStrictSchema:
    def test_structure(self):
        s = strict_schema({"name": {"type": "string"}}, ["name"])
        assert s["type"] == "object"
        assert s["additionalProperties"] is False
        assert s["required"] == ["name"]
        assert "name" in s["properties"]


class TestBuiltinTools:
    def test_registry_has_all(self):
        r = builtins()
        expected = ["shell_exec", "read_file", "write_file", "list_dir", "search_files"]
        for name in expected:
            assert r.get(name) is not None, f"missing builtin: {name}"

    def test_read_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("hello world")
            path = f.name
        try:
            tool = ReadFile()
            result = tool.execute({"path": path})
            assert result == "hello world"
        finally:
            Path(path).unlink()

    def test_read_file_missing(self):
        tool = ReadFile()
        result = tool.execute({"path": "/nonexistent/path/file.txt"})
        assert "error" in result

    def test_write_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = str(Path(d) / "sub" / "test.txt")
            tool = WriteFile()
            result = tool.execute({"path": path, "content": "test data"})
            assert "wrote" in result
            assert Path(path).read_text() == "test data"

    def test_list_dir(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "file.txt").write_text("x")
            (Path(d) / "subdir").mkdir()
            tool = ListDir()
            result = tool.execute({"path": d})
            assert "file.txt" in result
            assert "subdir/" in result
