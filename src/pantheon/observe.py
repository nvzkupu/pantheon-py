"""Structured logging, tracing, and cost estimation."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Callable

from .agent import Event
from .gateway import Usage


@dataclass
class Span:
    kind: str
    agent: str = ""
    tool: str = ""
    content: str = ""
    timestamp: str = ""


@dataclass
class Trace:
    id: str
    agent: str
    started_at: str = ""
    spans: list[Span] = field(default_factory=list)
    total_usage: Usage = field(default_factory=Usage)
    duration_ms: float = 0.0


class Tracker:
    """Collects traces across multiple agent invocations."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._traces: dict[str, Trace] = {}
        self._starts: dict[str, float] = {}

    def start(self, trace_id: str, agent_name: str) -> None:
        with self._lock:
            self._traces[trace_id] = Trace(
                id=trace_id, agent=agent_name,
                started_at=datetime.now(timezone.utc).isoformat())
            self._starts[trace_id] = time.monotonic()

    def add_span(self, trace_id: str, span: Span) -> None:
        with self._lock:
            trace = self._traces.get(trace_id)
            if trace:
                span.timestamp = datetime.now(timezone.utc).isoformat()
                trace.spans.append(span)

    def finish(self, trace_id: str, usage: Usage) -> Trace | None:
        with self._lock:
            trace = self._traces.get(trace_id)
            if not trace:
                return None
            trace.total_usage = usage
            start = self._starts.get(trace_id, time.monotonic())
            trace.duration_ms = (time.monotonic() - start) * 1000
            return trace

    def event_handler(self, trace_id: str) -> Callable[[Event], None]:
        def handler(e: Event) -> None:
            content = e.content[:500] + "..." if len(e.content) > 500 else e.content
            self.add_span(trace_id, Span(
                kind=e.kind, agent=e.agent, tool=e.tool, content=content))
        return handler


def cost_estimate(model: str, usage: Usage) -> float:
    """Rough USD cost estimate for a model and token usage."""
    if "opus" in model:
        in_rate, out_rate = 15.0, 75.0
    elif "codex" in model:
        in_rate, out_rate = 6.0, 24.0
    elif "nano" in model:
        in_rate, out_rate = 0.10, 0.40
    else:
        in_rate, out_rate = 3.0, 15.0
    return (usage.prompt_tokens * in_rate + usage.completion_tokens * out_rate) / 1_000_000
