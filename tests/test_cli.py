"""Tests for the Pantheon CLI entry point and command helpers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from pantheon import cli
from pantheon.agent import Agent
from pantheon.gateway import ChatResponse, Client, Usage
from pantheon.skill import Metadata, Skill


def _skill(
    name: str = "test",
    *,
    tools: list[str] | None = None,
    delegates: list[str] | None = None,
) -> Skill:
    return Skill(
        name=name,
        description=f"{name} skill",
        body=f"You are {name}.",
        path=f"/test/{name}/SKILL.md",
        metadata=Metadata(
            persona=f"{name.title()} Persona",
            model="test-model",
            temperature=0.5,
            max_tokens=1024,
            max_iterations=5,
            tools=tools or [],
            delegates=delegates or [],
        ),
    )


def _agent(
    name: str = "test",
    *,
    reply: str = "ok",
    tools: list[str] | None = None,
    delegates: list[str] | None = None,
) -> Agent:
    response = ChatResponse(content=reply, usage=Usage(1, 1, 2))
    client = MagicMock(spec=Client)
    client.chat = MagicMock(return_value=response)
    client.chat_stream = MagicMock(return_value=reply)
    client.chat_stream_full = MagicMock(return_value=response)
    return Agent(_skill(name, tools=tools, delegates=delegates), client)


@pytest.fixture(autouse=True)
def _patch_rich_consoles(monkeypatch):
    monkeypatch.setattr(cli, "console", MagicMock())
    monkeypatch.setattr(cli, "out", MagicMock())


class FakeStore:
    def __init__(self):
        self.saved: list[tuple[str, list]] = []

    def load(self, session_id: str):
        return []

    def save(self, session_id: str, history: list):
        self.saved.append((session_id, list(history)))


class TestMain:
    def test_defaults_to_warroom_when_no_command(self, monkeypatch):
        warroom = MagicMock()
        monkeypatch.setattr(cli.config, "load_env", lambda: None)
        monkeypatch.setattr(cli, "cmd_warroom", warroom)
        monkeypatch.setattr(cli.sys, "argv", ["pantheon"])

        cli.main()

        warroom.assert_called_once_with()

    def test_dispatches_list_command(self, monkeypatch):
        cmd_list = MagicMock()
        monkeypatch.setattr(cli.config, "load_env", lambda: None)
        monkeypatch.setattr(cli, "cmd_list", cmd_list)
        monkeypatch.setattr(cli.sys, "argv", ["pantheon", "list"])

        cli.main()

        cmd_list.assert_called_once_with()


class TestHelpers:
    def test_get_missing_agent_exits(self):
        with pytest.raises(SystemExit):
            cli._get({}, "unknown")

    def test_broadcast_preserves_name_order(self):
        athena = SimpleNamespace(
            name="athena",
            persona="Athena Persona",
            skill=SimpleNamespace(tool_names=[]),
            send=MagicMock(return_value="athena reply"),
            run=MagicMock(return_value="unused"),
        )
        kali = SimpleNamespace(
            name="kali",
            persona="Kali Persona",
            skill=SimpleNamespace(tool_names=["read_file"]),
            send=MagicMock(return_value="unused"),
            run=MagicMock(return_value="kali reply"),
        )
        agents = {"athena": athena, "kali": kali}

        cli._broadcast(agents, ["athena", "kali"], "hello")

        athena.send.assert_called_once_with("hello")
        kali.run.assert_called_once_with("hello")
        headings = [
            call.args[0]
            for call in cli.console.print.call_args_list
            if call.args and isinstance(call.args[0], str) and call.args[0].startswith("  ┌─ ")
        ]
        assert headings[0].startswith("  ┌─ athena")
        assert headings[1].startswith("  ┌─ kali")


class TestCommands:
    def test_cmd_list_prints_agent_table(self, monkeypatch):
        agents = {"athena": _agent("athena"), "kali": _agent("kali")}
        monkeypatch.setattr(cli, "_agents", lambda: agents)

        cli.cmd_list()

        cli.out.print.assert_called_once()
        table = cli.out.print.call_args.args[0]
        assert len(table.rows) == 2

    def test_cmd_ask_streams_reply(self, monkeypatch):
        athena = _agent("athena", reply="streamed")
        monkeypatch.setattr(cli, "_agents", lambda: {"athena": athena})

        cli.cmd_ask("athena", "hello")

        athena.client.chat_stream.assert_called_once()

    def test_cmd_run_prints_reply(self, monkeypatch):
        athena = _agent("athena", reply="done")
        equip = MagicMock()
        monkeypatch.setattr(cli, "_agents", lambda: {"athena": athena})
        monkeypatch.setattr(cli, "_equip", equip)

        cli.cmd_run("athena", "do work")

        equip.assert_called_once_with(athena)
        cli.out.print.assert_called_once_with("done")

    def test_cmd_team_exits_without_delegates(self, monkeypatch):
        freya = _agent("freya", delegates=[])
        monkeypatch.setattr(cli, "_agents", lambda: {"freya": freya})

        with pytest.raises(SystemExit):
            cli.cmd_team("freya", "coordinate")

    def test_cmd_team_runs_with_delegate(self, monkeypatch):
        freya = _agent("freya", reply="coordinated", delegates=["kali"])
        kali = _agent("kali", reply="specialist")
        monkeypatch.setattr(cli, "_agents", lambda: {"freya": freya, "kali": kali})
        monkeypatch.setattr(cli, "_equip", lambda _agent: None)

        cli.cmd_team("freya", "coordinate")

        cli.out.print.assert_called_once_with("coordinated")

    def test_cmd_pipe_runs_pipeline(self, monkeypatch):
        athena = _agent("athena", reply="from-athena")
        kali = _agent("kali", reply="final")
        monkeypatch.setattr(cli, "_agents", lambda: {"athena": athena, "kali": kali})
        monkeypatch.setattr(cli, "_equip", lambda _agent: None)
        monkeypatch.setattr(cli.config, "verbose", lambda: False)

        cli.cmd_pipe("athena,kali", "start")

        cli.out.print.assert_called_once_with("final")
        messages = kali.client.chat.call_args.kwargs["messages"]
        user_msg = next(message for message in messages if message.role == "user")
        assert user_msg.content == "from-athena"

    def test_cmd_review_requires_two_agents(self, monkeypatch):
        monkeypatch.setattr(cli, "_agents", lambda: {"athena": _agent("athena")})

        with pytest.raises(SystemExit):
            cli.cmd_review("athena", "review")

    def test_cmd_review_runs_and_prints_result(self, monkeypatch):
        kali = _agent("kali", reply="security ok")
        themis = _agent("themis", reply="tests ok")
        athena = _agent("athena", reply="all clear")
        monkeypatch.setattr(
            cli,
            "_agents",
            lambda: {"kali": kali, "themis": themis, "athena": athena},
        )
        monkeypatch.setattr(cli, "_equip", lambda _agent: None)
        monkeypatch.setattr(cli.config, "verbose", lambda: False)

        cli.cmd_review("kali,themis,athena", "review this")

        cli.out.print.assert_called_once_with("all clear")

    def test_cmd_chat_handles_reset_save_and_quit(self, monkeypatch):
        athena = _agent("athena")
        store = FakeStore()
        inputs = iter(["/reset", "/save", "/quit"])
        monkeypatch.setattr(cli, "_agents", lambda: {"athena": athena})
        monkeypatch.setattr(cli, "FileStore", lambda _directory: store)
        monkeypatch.setattr(cli.config, "memory_dir", lambda: ".memory")
        monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))

        cli.cmd_chat("athena")

        assert len(store.saved) == 2
        assert all(history[0].role == "system" for _, history in store.saved)

    def test_cmd_warroom_handles_list_broadcast_and_direct_message(self, monkeypatch):
        athena = _agent("athena", reply="athena reply")
        kali = _agent("kali", reply="kali reply", tools=["read_file"])
        inputs = iter(["/list", "/all hello", "@athena hi", "/quit"])
        broadcast = MagicMock()
        monkeypatch.setattr(cli, "_agents", lambda: {"athena": athena, "kali": kali})
        monkeypatch.setattr(cli, "_equip", lambda _agent: None)
        monkeypatch.setattr(cli.config, "verbose", lambda: False)
        monkeypatch.setattr(cli, "_broadcast", broadcast)
        monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))

        cli.cmd_warroom()

        broadcast.assert_called_once_with({"athena": athena, "kali": kali}, ["athena", "kali"], "hello")
        athena.client.chat_stream.assert_called_once()
