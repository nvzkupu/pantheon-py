"""Tests for multi-agent orchestration — Team, Pipeline, Review, AgentTool."""

from unittest.mock import MagicMock

import pytest

from pantheon.agent import Agent, Event
from pantheon.gateway import Client, ChatResponse, Usage
from pantheon.orchestrate import AgentTool, Team, Pipeline, Review, ReviewResult
from pantheon.skill import Skill, Metadata


def _skill(name: str = "test", tools: list[str] | None = None,
           delegates: list[str] | None = None) -> Skill:
    return Skill(
        name=name, description=f"{name} skill", body=f"You are {name}.",
        path=f"/test/{name}/SKILL.md",
        metadata=Metadata(
            persona=f"{name.title()} Persona", model="test-model",
            temperature=0.5, max_tokens=1024, max_iterations=5,
            tools=tools or [], delegates=delegates or [],
        ),
    )


def _agent(name: str = "test", reply: str = "ok",
           tools: list[str] | None = None,
           delegates: list[str] | None = None) -> Agent:
    """Create an agent whose run() returns a fixed reply."""
    resp = ChatResponse(content=reply, usage=Usage(1, 1, 2))
    client = MagicMock(spec=Client)
    client.chat = MagicMock(return_value=resp)
    client.chat_stream_full = MagicMock(return_value=resp)
    return Agent(_skill(name, tools, delegates), client)


class TestAgentTool:
    def test_name(self):
        a = _agent("kali")
        tool = AgentTool(a)
        assert tool.name() == "ask_kali"

    def test_description_includes_persona(self):
        a = _agent("kali")
        tool = AgentTool(a)
        desc = tool.description()
        assert "Kali Persona" in desc
        assert "kali skill" in desc

    def test_parameters_schema(self):
        tool = AgentTool(_agent())
        params = tool.parameters()
        assert params["type"] == "object"
        assert "task" in params["properties"]
        assert params["required"] == ["task"]
        assert params["additionalProperties"] is False

    def test_execute_delegates_to_agent(self):
        a = _agent("kali", reply="audit complete")
        tool = AgentTool(a)
        result = tool.execute({"task": "review this code"})
        assert result == "audit complete"

    def test_execute_handles_error(self):
        a = _agent("kali")
        a.client.chat.side_effect = RuntimeError("boom")
        tool = AgentTool(a)
        result = tool.execute({"task": "fail"})
        assert "error" in result

    def test_definition_format(self):
        tool = AgentTool(_agent("test"))
        defn = tool.definition()
        assert defn["type"] == "function"
        assert defn["function"]["name"] == "ask_test"
        assert defn["function"]["strict"] is True


class TestTeam:
    def test_setup_registers_agent_tools(self):
        lead = _agent("freya", tools=["read_file"])
        specialists = [_agent("kali"), _agent("nuwa")]
        team = Team(lead, specialists)
        team.setup()

        assert lead.tools.get("ask_kali") is not None
        assert lead.tools.get("ask_nuwa") is not None

    def test_setup_adds_system_suffix(self):
        lead = _agent("freya")
        specialists = [_agent("kali")]
        team = Team(lead, specialists)
        team.setup()

        system_msg = lead.history[0].content
        assert "coordinator" in system_msg
        assert "ask_kali" in system_msg

    def test_run_delegates_to_lead(self):
        lead = _agent("freya", reply="coordinated result")
        team = Team(lead, [_agent("kali")])
        team.setup()

        result = team.run("do something")
        assert result == "coordinated result"

    def test_event_handler_propagates(self):
        lead = _agent("freya")
        spec = _agent("kali")
        team = Team(lead, [spec])

        events: list[Event] = []
        team.on_event = events.append
        team.setup()

        assert lead.on_event is not None
        assert spec.on_event is not None


class TestPipeline:
    def test_sequential_execution(self):
        a1 = _agent("stage1", reply="stage1 output")
        a2 = _agent("stage2", reply="stage2 output")
        pipe = Pipeline("test-pipe", [a1, a2])
        result = pipe.run("initial input")
        assert result == "stage2 output"

    def test_passes_output_to_next(self):
        a1 = _agent("stage1", reply="from_a1")
        a2 = _agent("stage2", reply="final")
        pipe = Pipeline("test", [a1, a2])
        pipe.run("start")

        last_call = a2.client.chat.call_args
        messages = last_call.kwargs["messages"]
        user_msg = next(m for m in messages if m.role == "user")
        assert user_msg.content == "from_a1"

    def test_error_propagation(self):
        a1 = _agent("stage1")
        a1.client.chat.side_effect = RuntimeError("stage1 failed")

        pipe = Pipeline("failing", [a1, _agent("stage2")])
        with pytest.raises(RuntimeError, match="stage 0.*stage1"):
            pipe.run("go")

    def test_single_stage(self):
        a = _agent("solo", reply="done")
        pipe = Pipeline("single", [a])
        assert pipe.run("go") == "done"


class TestReview:
    def test_fan_out_and_synthesize(self):
        r1 = _agent("kali", reply="security ok")
        r2 = _agent("themis", reply="tests ok")
        synth = _agent("athena", reply="all clear")

        rev = Review(synth, [r1, r2])
        result = rev.run("review this")
        assert result == "all clear"

    def test_synthesizer_receives_all_reviews(self):
        r1 = _agent("kali", reply="finding-A")
        r2 = _agent("pele", reply="finding-B")
        synth = _agent("athena", reply="synthesis")

        rev = Review(synth, [r1, r2])
        rev.run("review this")

        synth_call = synth.client.chat.call_args
        messages = synth_call.kwargs["messages"]
        user_msg = next(m for m in messages if m.role == "user")
        assert "finding-A" in user_msg.content
        assert "finding-B" in user_msg.content
        assert "kali" in user_msg.content
        assert "pele" in user_msg.content

    def test_handles_reviewer_error(self):
        r1 = _agent("kali")
        r1.client.chat.side_effect = RuntimeError("boom")
        r2 = _agent("themis", reply="ok")
        synth = _agent("athena", reply="partial")

        rev = Review(synth, [r1, r2])
        result = rev.run("review")
        assert result == "partial"

    def test_fan_out_preserves_order(self):
        reviewers = [_agent(f"r{i}", reply=f"output-{i}") for i in range(4)]
        synth = _agent("synth", reply="done")

        rev = Review(synth, reviewers)
        results = rev._fan_out("test")
        assert [r.name for r in results] == [f"r{i}" for i in range(4)]


class TestReviewResult:
    def test_dataclass(self):
        r = ReviewResult(name="kali", persona="Protector",
                         output="ok", elapsed=1.5)
        assert r.name == "kali"
        assert r.error == ""
        assert r.elapsed == 1.5

    def test_error_result(self):
        r = ReviewResult(name="kali", persona="Protector",
                         output="", error="failed", elapsed=0.1)
        assert r.error == "failed"
