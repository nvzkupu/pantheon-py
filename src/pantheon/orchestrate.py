"""Multi-agent orchestration: teams, pipelines, fan-out review."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable
from dataclasses import dataclass
from typing import Any

from .agent import Agent, Event
from .tools import Tool


class AgentTool(Tool):
    """Wraps an agent as a tool so coordinators can delegate work."""

    def __init__(self, agent: Agent) -> None:
        self._agent = agent

    def name(self) -> str:
        return f"ask_{self._agent.name}"

    def description(self) -> str:
        return (f"Delegate to {self._agent.name} ({self._agent.persona}). "
                f"Specializes in: {self._agent.use_for}")

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "Task for this specialist"},
            },
            "required": ["task"],
        }

    def execute(self, args: dict[str, Any]) -> str:
        self._agent.reset()
        try:
            return self._agent.run(args["task"])
        except Exception as e:
            return f"specialist {self._agent.name} error: {e}"


class Team:
    """Coordinator with specialist delegates using agent-as-tool pattern."""

    def __init__(self, lead: Agent, specialists: list[Agent]) -> None:
        self.lead = lead
        self.specialists = {s.name: s for s in specialists}
        self.on_event: Callable[[Event], None] | None = None

    def setup(self) -> None:
        for spec in self.specialists.values():
            self.lead.tools.register(AgentTool(spec))

        roster = "\n".join(
            f"- ask_{s.name}: {s.name} ({s.persona}) — {s.use_for}"
            for s in self.specialists.values())

        self.lead.skill.body += f"""

You coordinate a specialist team. Available specialists:

{roster}

RULES:
1. Break complex tasks into subtasks and delegate to the best specialist.
2. Synthesize specialist responses into a coherent answer.
3. Attribute insights to the specialist who provided them.
4. For simple questions you can answer directly."""

        self.lead.reset()

        if self.on_event:
            self.lead.on_event = self.on_event
            for s in self.specialists.values():
                s.on_event = self.on_event

    def run(self, msg: str) -> str:
        return self.lead.run(msg)


class Pipeline:
    """Sequential pipeline: output of each agent feeds into the next."""

    def __init__(self, name: str, stages: list[Agent]) -> None:
        self.name = name
        self.stages = stages

    def run(self, input_text: str) -> str:
        current = input_text
        for i, agent in enumerate(self.stages):
            agent.reset()
            try:
                current = agent.run(current)
            except Exception as e:
                raise RuntimeError(
                    f"pipeline '{self.name}' stage {i} ({agent.name}): {e}") from e
        return current


@dataclass
class ReviewResult:
    name: str
    persona: str
    output: str
    error: str = ""
    elapsed: float = 0.0


class Review:
    """Fan-out to multiple reviewers in parallel, then synthesize."""

    def __init__(self, synthesizer: Agent, reviewers: list[Agent]) -> None:
        self.synthesizer = synthesizer
        self.reviewers = reviewers

    def run(self, input_text: str) -> str:
        results = self._fan_out(input_text)
        return self._synthesize(input_text, results)

    def _fan_out(self, input_text: str) -> list[ReviewResult]:
        results: list[ReviewResult] = [ReviewResult("", "", "")] * len(self.reviewers)

        def review(idx: int, agent: Agent) -> None:
            start = time.monotonic()
            agent.reset()
            try:
                output = agent.run(input_text)
                results[idx] = ReviewResult(
                    agent.name, agent.persona, output,
                    elapsed=time.monotonic() - start)
            except Exception as e:
                results[idx] = ReviewResult(
                    agent.name, agent.persona, "",
                    error=str(e), elapsed=time.monotonic() - start)

        with ThreadPoolExecutor() as pool:
            futures = [pool.submit(review, i, a) for i, a in enumerate(self.reviewers)]
            for f in as_completed(futures):
                f.result()

        return results

    def _synthesize(self, input_text: str, results: list[ReviewResult]) -> str:
        reviews = "\n\n".join(
            f"=== {r.name} ({r.persona}) ===\n"
            + (f"ERROR: {r.error}" if r.error else r.output)
            for r in results)

        prompt = (
            f"Synthesize these specialist reviews into a single, actionable response.\n\n"
            f"Original request:\n{input_text}\n\n"
            f"Reviews:\n{reviews}\n\n"
            f"Provide a unified response with the most important points from each reviewer.")

        self.synthesizer.reset()
        return self.synthesizer.run(prompt)
