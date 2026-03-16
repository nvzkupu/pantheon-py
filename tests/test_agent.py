"""Tests for the agent runtime — ReAct loop, tool dispatch, lifecycle."""

from unittest.mock import MagicMock

import pytest

from pantheon.agent import Agent, Event, load_all, equip_tools
from pantheon.gateway import Client, Message, ChatResponse, Usage
from pantheon.skill import Skill, Metadata
from pantheon.tools import Registry, Tool, strict_schema


def _skill(name: str = "test", tools: list[str] | None = None,
           delegates: list[str] | None = None) -> Skill:
    return Skill(
        name=name, description="test skill", body="You are a test agent.",
        path="/test/SKILL.md",
        metadata=Metadata(
            persona="Test Persona", model="test-model",
            temperature=0.5, max_tokens=1024, max_iterations=5,
            tools=tools or [], delegates=delegates or [],
        ),
    )


def _client_returning(*responses: ChatResponse) -> Client:
    client = MagicMock(spec=Client)
    client.chat = MagicMock(side_effect=list(responses))
    client.chat_stream = MagicMock(
        side_effect=[r.content for r in responses])
    client.chat_stream_full = MagicMock(side_effect=list(responses))
    return client


class _EchoTool(Tool):
    def name(self) -> str:
        return "echo"

    def description(self) -> str:
        return "Echo"

    def parameters(self) -> dict:
        return strict_schema(
            {"msg": {"type": "string", "description": "Message"}}, ["msg"])

    def execute(self, args: dict) -> str:
        return args["msg"]


class TestAgentProperties:
    def test_name_from_skill(self):
        a = Agent(_skill("athena"), _client_returning())
        assert a.name == "athena"

    def test_persona_from_skill(self):
        a = Agent(_skill(), _client_returning())
        assert a.persona == "Test Persona"

    def test_model_from_skill(self):
        a = Agent(_skill(), _client_returning())
        assert a.model == "test-model"

    def test_use_for_from_description(self):
        a = Agent(_skill(), _client_returning())
        assert a.use_for == "test skill"


class TestAgentReset:
    def test_initializes_with_system_message(self):
        a = Agent(_skill(), _client_returning())
        assert len(a.history) == 1
        assert a.history[0].role == "system"
        assert a.history[0].content == "You are a test agent."

    def test_reset_clears_and_restores_system(self):
        a = Agent(_skill(), _client_returning())
        a._history.append(Message(role="user", content="extra"))
        assert len(a.history) == 2
        a.reset()
        assert len(a.history) == 1
        assert a.history[0].role == "system"

    def test_system_suffix_appended(self):
        a = Agent(_skill(), _client_returning())
        a.system_suffix = "\nExtra instructions."
        a.reset()
        assert a.history[0].content.endswith("\nExtra instructions.")


class TestAgentSend:
    def test_send_appends_messages(self):
        resp = ChatResponse(content="reply", usage=Usage())
        client = _client_returning(resp)
        a = Agent(_skill(), client)

        result = a.send("hello")
        assert result == "reply"
        assert len(a.history) == 3
        assert a.history[1].role == "user"
        assert a.history[2].role == "assistant"

    def test_send_stream_appends_messages(self):
        client = _client_returning()
        client.chat_stream = MagicMock(return_value="streamed")
        a = Agent(_skill(), client)

        chunks: list[str] = []
        result = a.send_stream("hello", on_chunk=chunks.append)
        assert result == "streamed"
        assert a.history[-1].role == "assistant"


class TestAgentEmit:
    def test_emit_calls_handler(self):
        a = Agent(_skill(), _client_returning())
        events: list[Event] = []
        a.on_event = events.append

        a.emit("test_event", content="data")
        assert len(events) == 1
        assert events[0].kind == "test_event"
        assert events[0].agent == "test"
        assert events[0].content == "data"

    def test_emit_no_handler_is_noop(self):
        a = Agent(_skill(), _client_returning())
        a.on_event = None
        a.emit("test_event")


class TestAgentReactLoop:
    def test_simple_reply_no_tools(self):
        resp = ChatResponse(content="answer", usage=Usage(1, 2, 3))
        client = _client_returning(resp)
        a = Agent(_skill(), client)

        result = a.run("question")
        assert result == "answer"

    def test_tool_call_then_reply(self):
        tool_resp = ChatResponse(
            content="", usage=Usage(5, 5, 10),
            tool_calls=[{
                "id": "tc-1", "type": "function",
                "function": {"name": "echo", "arguments": '{"msg":"hello"}'},
            }],
        )
        final_resp = ChatResponse(content="done", usage=Usage(10, 5, 15))
        client = _client_returning(tool_resp, final_resp)
        a = Agent(_skill(tools=["echo"]), client)
        a.tools.register(_EchoTool())

        result = a.run("test")
        assert result == "done"
        assert client.chat.call_count == 2

    def test_max_iterations_raises(self):
        tool_resp = ChatResponse(
            content="", usage=Usage(),
            tool_calls=[{
                "id": "tc-1", "type": "function",
                "function": {"name": "echo", "arguments": '{"msg":"loop"}'},
            }],
        )
        client = MagicMock(spec=Client)
        client.chat = MagicMock(return_value=tool_resp)

        s = _skill(tools=["echo"])
        s.metadata.max_iterations = 3
        a = Agent(s, client)
        a.tools.register(_EchoTool())

        with pytest.raises(RuntimeError, match="max iterations"):
            a.run("infinite loop")
        assert client.chat.call_count == 3

    def test_run_stream_with_on_chunk(self):
        resp = ChatResponse(content="streamed", usage=Usage(1, 1, 2))
        client = _client_returning(resp)
        client.chat_stream_full = MagicMock(return_value=resp)
        a = Agent(_skill(), client)

        chunks: list[str] = []
        result = a.run_stream("test", on_chunk=chunks.append)
        assert result == "streamed"
        client.chat_stream_full.assert_called_once()

    def test_emits_events_during_loop(self):
        tool_resp = ChatResponse(
            content="", usage=Usage(),
            tool_calls=[{
                "id": "tc-1", "type": "function",
                "function": {"name": "echo", "arguments": '{"msg":"hi"}'},
            }],
        )
        final_resp = ChatResponse(content="done", usage=Usage(5, 3, 8))
        client = _client_returning(tool_resp, final_resp)

        a = Agent(_skill(tools=["echo"]), client)
        a.tools.register(_EchoTool())

        events: list[Event] = []
        a.on_event = events.append
        a.run("test")

        kinds = [e.kind for e in events]
        assert "tool_call" in kinds
        assert "tool_result" in kinds
        assert "reply" in kinds


class TestLoadAll:
    def test_loads_skills_as_agents(self, tmp_path):
        skill_dir = tmp_path / "test_agent"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: myagent\ndescription: test\n"
            "metadata:\n  persona: Tester\n---\n\n# Test")

        client = MagicMock(spec=Client)
        agents = load_all(str(tmp_path), client)
        assert "myagent" in agents
        assert agents["myagent"].name == "myagent"


class TestEquipTools:
    def test_registers_matching_tools(self):
        a = Agent(_skill(tools=["echo"]), _client_returning())
        registry = Registry()
        registry.register(_EchoTool())

        equip_tools(a, registry)
        assert a.tools.get("echo") is not None

    def test_warns_on_missing_tool(self, caplog):
        a = Agent(_skill(tools=["nonexistent"]), _client_returning())
        registry = Registry()

        with caplog.at_level("WARNING"):
            equip_tools(a, registry)
        assert "not found" in caplog.text

    def test_uses_builtins_by_default(self):
        a = Agent(_skill(tools=["read_file"]), _client_returning())
        equip_tools(a)
        assert a.tools.get("read_file") is not None
