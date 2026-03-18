"""OpenAI-compatible LLM gateway client with streaming and tool call support.

Drop-in replaceable with litellm for 100+ provider support:
    pip install pantheon[litellm]
"""

from __future__ import annotations

import json
import random
import time as _time
from dataclasses import dataclass, field
from typing import Any, Callable

import requests

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_MAX_RETRIES = 3
_BASE_DELAY = 1.0
_MAX_DELAY = 30.0


def _retry_delay(attempt: int, response: requests.Response | None = None) -> float:
    """Compute backoff delay with jitter, respecting Retry-After header."""
    if response is not None:
        ra = response.headers.get("Retry-After")
        if ra and ra.isdigit():
            return float(ra)
    delay = min(_BASE_DELAY * (2 ** attempt), _MAX_DELAY)
    return delay + random.uniform(0, delay / 2)


@dataclass
class Message:
    role: str
    content: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_call_id: str = ""
    name: str = ""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"role": self.role}
        if self.content or not self.tool_calls:
            d["content"] = self.content
        else:
            d["content"] = None
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
        if not api_key:
            raise ValueError(
                "API key is required. Set API_KEY or NVIDIA_API_KEY"
                " in your environment, or pass it to Client() directly.")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        self.session.headers["Authorization"] = f"Bearer {api_key}"

    def close(self) -> None:
        self.session.close()

    def __enter__(self) -> Client:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def chat(self, *, model: str, messages: list[Message],
             temperature: float = 0.7, max_tokens: int = 4096,
             tools: list[dict] | None = None,
             tool_choice: str | dict | None = None) -> ChatResponse:
        payload = self._build_payload(
            model, messages, temperature, max_tokens,
            tools, tool_choice,
        )
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            resp = self.session.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                timeout=self.timeout,
            )
            if resp.status_code == 200:
                return self._parse_response(resp.json())
            if resp.status_code not in _RETRYABLE_STATUS or attempt == _MAX_RETRIES - 1:
                resp.raise_for_status()
            last_exc = requests.HTTPError(response=resp)
            _time.sleep(_retry_delay(attempt, resp))
        raise last_exc  # type: ignore[misc]

    def chat_stream(self, *, model: str, messages: list[Message],
                    temperature: float = 0.7, max_tokens: int = 4096,
                    on_chunk: Callable[[str], None] | None = None) -> str:
        result = self.chat_stream_full(
            model=model, messages=messages, temperature=temperature,
            max_tokens=max_tokens, on_chunk=on_chunk)
        return result.content

    def chat_stream_full(self, *, model: str, messages: list[Message],
                         temperature: float = 0.7, max_tokens: int = 4096,
                         tools: list[dict] | None = None,
                         on_chunk: Callable[[str], None] | None = None) -> ChatResponse:
        """Stream a response, accumulating both content and tool call deltas."""
        payload = self._build_payload(model, messages, temperature, max_tokens, tools)
        payload["stream"] = True

        resp: requests.Response | None = None
        for attempt in range(_MAX_RETRIES):
            resp = self.session.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                stream=True,
                timeout=self.timeout,
            )
            if resp.status_code == 200:
                break
            if resp.status_code not in _RETRYABLE_STATUS or attempt == _MAX_RETRIES - 1:
                resp.raise_for_status()
            _time.sleep(_retry_delay(attempt, resp))
        if resp is None:
            raise RuntimeError("all retry attempts failed")

        with resp:
            content_parts: list[str] = []
            tool_calls: dict[int, dict] = {}
            usage = Usage()

            for line in resp.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data: "):
                    continue
                data = line[6:]
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    text = delta.get("content", "")
                    if text:
                        content_parts.append(text)
                        if on_chunk:
                            on_chunk(text)
                    for tc_delta in delta.get("tool_calls", []):
                        idx = tc_delta.get("index", 0)
                        if idx in tool_calls:
                            tool_calls[idx]["function"]["arguments"] += (
                                tc_delta.get("function", {}).get(
                                    "arguments", "",
                                ))
                        else:
                            tool_calls[idx] = {
                                "id": tc_delta.get("id", ""),
                                "type": tc_delta.get("type", "function"),
                                "function": {
                                    "name": tc_delta.get(
                                        "function", {},
                                    ).get("name", ""),
                                    "arguments": tc_delta.get(
                                        "function", {},
                                    ).get("arguments", ""),
                                },
                            }
                    chunk_usage = chunk.get("usage")
                    if chunk_usage:
                        usage = Usage(
                            prompt_tokens=chunk_usage.get("prompt_tokens", 0),
                            completion_tokens=chunk_usage.get("completion_tokens", 0),
                            total_tokens=chunk_usage.get("total_tokens", 0),
                        )
                except (json.JSONDecodeError, IndexError):
                    continue

            return ChatResponse(
                content="".join(content_parts),
                tool_calls=[tool_calls[idx] for idx in sorted(tool_calls)],
                usage=usage,
            )

    def _build_payload(self, model: str, messages: list[Message],
                       temperature: float, max_tokens: int,
                       tools: list[dict] | None = None,
                       tool_choice: str | dict | None = None) -> dict:
        payload: dict[str, Any] = {
            "model": model,
            "messages": [m.to_dict() for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = tools
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice
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
