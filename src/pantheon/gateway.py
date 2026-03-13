"""OpenAI-compatible LLM gateway client with streaming and tool call support.

Drop-in replaceable with litellm for 100+ provider support:
    pip install pantheon[litellm]
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable

import requests


@dataclass
class Message:
    role: str
    content: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_call_id: str = ""
    name: str = ""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.tool_calls:
            d["tool_calls"] = self.tool_calls
        if self.tool_call_id:
            d["tool_call_id"] = self.tool_call_id
        if self.name:
            d["name"] = self.name
        return d


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class ChatResponse:
    content: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    finish_reason: str = ""


class Client:
    def __init__(self, base_url: str, api_key: str, timeout: int = 300):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.session = requests.Session()
        self.session.timeout = timeout
        self.session.headers.update({"Content-Type": "application/json"})
        if api_key:
            self.session.headers["Authorization"] = f"Bearer {api_key}"

    def chat(self, *, model: str, messages: list[Message],
             temperature: float = 0.7, max_tokens: int = 4096,
             tools: list[dict] | None = None) -> ChatResponse:
        payload = self._build_payload(model, messages, temperature, max_tokens, tools)
        resp = self.session.post(f"{self.base_url}/chat/completions", json=payload)
        resp.raise_for_status()
        return self._parse_response(resp.json())

    def chat_stream(self, *, model: str, messages: list[Message],
                    temperature: float = 0.7, max_tokens: int = 4096,
                    on_chunk: Callable[[str], None] | None = None) -> str:
        payload = self._build_payload(model, messages, temperature, max_tokens)
        payload["stream"] = True
        resp = self.session.post(
            f"{self.base_url}/chat/completions", json=payload, stream=True)
        resp.raise_for_status()

        full = []
        for line in resp.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data: "):
                continue
            data = line[6:]
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
                delta = chunk.get("choices", [{}])[0].get("delta", {})
                content = delta.get("content", "")
                if content:
                    full.append(content)
                    if on_chunk:
                        on_chunk(content)
            except (json.JSONDecodeError, IndexError):
                continue
        return "".join(full)

    def _build_payload(self, model: str, messages: list[Message],
                       temperature: float, max_tokens: int,
                       tools: list[dict] | None = None) -> dict:
        payload: dict[str, Any] = {
            "model": model,
            "messages": [m.to_dict() for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = tools
        return payload

    def _parse_response(self, data: dict) -> ChatResponse:
        choice = data.get("choices", [{}])[0]
        msg = choice.get("message", {})
        usage_raw = data.get("usage", {})
        return ChatResponse(
            content=msg.get("content", ""),
            tool_calls=msg.get("tool_calls", []),
            usage=Usage(
                prompt_tokens=usage_raw.get("prompt_tokens", 0),
                completion_tokens=usage_raw.get("completion_tokens", 0),
                total_tokens=usage_raw.get("total_tokens", 0),
            ),
            finish_reason=choice.get("finish_reason", ""),
        )
