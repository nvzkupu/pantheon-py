"""Agent runtime — load from skills, ReAct loop, streaming."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

from .gateway import Client, Message, Usage
from .skill import Skill, discover_map
from .tools import Registry, builtins

_log = logging.getLogger(__name__)


@dataclass
class Event:
    kind: str
    agent: str = ""
    tool: str = ""
    content: str = ""
    usage: Usage | None = None


class Agent:
    def __init__(self, skill: Skill, client: Client) -> None:
        self.skill = skill
        self.client = client
        self.tools = Registry()
        self.on_event: Callable[[Event], None] | None = None
        self.system_suffix: str = ""
        self._history: list[Message] = []
        self.reset()

    @property
    def name(self) -> str:
        return self.skill.name

    @property
    def history(self) -> list[Message]:
        return self._history

    @property
    def persona(self) -> str:
        return self.skill.persona

    @property
    def model(self) -> str:
        return self.skill.model

    @property
    def use_for(self) -> str:
        return self.skill.description

    def emit(self, kind: str, **kw: Any) -> None:
        if self.on_event:
            self.on_event(Event(kind=kind, agent=self.name, **kw))

    def reset(self) -> None:
        body = self.skill.body
        if self.system_suffix:
            body += self.system_suffix
        self._history = [Message(role="system", content=body)]

    def send(self, msg: str) -> str:
        self._history.append(Message(role="user", content=msg))
        resp = self.client.chat(
            model=self.model, messages=self._history,
            temperature=self.skill.temperature, max_tokens=self.skill.max_tokens)
        self._history.append(Message(role="assistant", content=resp.content))
        return resp.content

    def send_stream(
        self, msg: str, on_chunk: Callable[[str], None] | None = None,
    ) -> str:
        self._history.append(Message(role="user", content=msg))
        full = self.client.chat_stream(
            model=self.model, messages=self._history,
            temperature=self.skill.temperature, max_tokens=self.skill.max_tokens,
            on_chunk=on_chunk)
        self._history.append(Message(role="assistant", content=full))
        return full

    def run(self, msg: str) -> str:
        """Full ReAct loop: reason → call tools → observe → repeat."""
        return self.run_stream(msg)

    def run_stream(
        self, msg: str, on_chunk: Callable[[str], None] | None = None,
    ) -> str:
        """ReAct loop with optional streaming. Streams content deltas via on_chunk."""
        self._history.append(Message(role="user", content=msg))

        tool_defs = self.tools.definitions() or None
        total = Usage()

        for i in range(self.skill.max_iterations):
            if on_chunk is not None:
                resp = self.client.chat_stream_full(
                    model=self.model,
                    messages=self._history,
                    temperature=self.skill.temperature,
                    max_tokens=self.skill.max_tokens,
                    tools=tool_defs,
                    on_chunk=on_chunk,
                )
            else:
                resp = self.client.chat(
                    model=self.model,
                    messages=self._history,
                    temperature=self.skill.temperature,
                    max_tokens=self.skill.max_tokens,
                    tools=tool_defs,
                )

            total.prompt_tokens += resp.usage.prompt_tokens
            total.completion_tokens += resp.usage.completion_tokens
            total.total_tokens += resp.usage.total_tokens

            if resp.tool_calls:
                self._history.append(Message(
                    role="assistant", content=resp.content,
                    tool_calls=resp.tool_calls))

                for tc in resp.tool_calls:
                    fn = tc.get("function", {})
                    self.emit("tool_call", tool=fn.get("name", ""),
                              content=fn.get("arguments", ""))

                results = self.tools.execute_all(resp.tool_calls)
                for r in results:
                    self.emit("tool_result", content=r["content"])
                    self._history.append(Message(
                        role="tool", content=r["content"],
                        tool_call_id=r.get("tool_call_id", "")))
                continue

            self._history.append(Message(role="assistant", content=resp.content))
            self.emit("reply", content=resp.content, usage=total)
            return resp.content

        raise RuntimeError(
            f"agent '{self.name}' hit max iterations"
            f" ({self.skill.max_iterations});"
            " increase max_iterations or simplify the task")


def load_all(directory: str, client: Client) -> dict[str, Agent]:
    skills = discover_map(directory)
    return {name: Agent(s, client) for name, s in skills.items()}


def equip_tools(agent: Agent, registry: Registry | None = None) -> None:
    registry = registry or builtins()
    for name in agent.skill.tool_names:
        tool = registry.get(name)
        if tool:
            agent.tools.register(tool)
        else:
            _log.warning(
                "agent '%s': tool '%s' not found in registry",
                agent.name, name,
            )
