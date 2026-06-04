"""Provider-agnostic LLM interface.

Every provider (Groq, OpenAI, Ollama) implements `LLMProvider` so the rest of
the app never depends on a specific vendor. Swap providers via the LLM_PROVIDER
env var — no code changes needed.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator


class LLMMessage(dict):
    """A chat message: {"role": "system"|"user"|"assistant", "content": str}."""

    def __init__(self, role: str, content: str):
        super().__init__(role=role, content=content)


class LLMProvider(ABC):
    """Common interface all LLM backends implement."""

    name: str = "base"

    @abstractmethod
    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.3,
        max_tokens: int = 8000,
        fast: bool = False,
        json_mode: bool = False,
    ) -> str:
        """Return the assistant's text response for the given chat messages."""
        ...

    async def stream(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.3,
        max_tokens: int = 8000,
        fast: bool = False,
    ) -> AsyncIterator[str]:
        """Yield text deltas as the model generates.

        Providers should override this with a real streaming implementation.
        The default falls back to a single `complete()` and yields the result
        as one chunk, so any provider remains usable even without streaming.
        """
        full = await self.complete(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            fast=fast,
        )
        yield full

    async def complete_json(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.2,
        max_tokens: int = 8000,
        fast: bool = False,
        retries: int = 2,
    ) -> dict[str, Any]:
        """Return parsed JSON, retrying with a repair hint on malformed output."""
        last_err: Exception | None = None
        convo = list(messages)
        for attempt in range(retries + 1):
            raw = await self.complete(
                convo,
                temperature=temperature,
                max_tokens=max_tokens,
                fast=fast,
                json_mode=True,
            )
            cleaned = _strip_json(raw)
            try:
                return json.loads(cleaned)
            except json.JSONDecodeError as exc:
                last_err = exc
                convo = list(messages) + [
                    {"role": "assistant", "content": raw},
                    {
                        "role": "user",
                        "content": (
                            "Your previous reply was not valid JSON "
                            f"({exc}). Return ONLY corrected, valid JSON. "
                            "No markdown, no code fences, no commentary."
                        ),
                    },
                ]
        raise ValueError(f"LLM did not return valid JSON after retries: {last_err}")


def _strip_json(text: str) -> str:
    """Remove code fences / <think> blocks / stray prose around a JSON payload."""
    t = text.strip()
    if "<think>" in t and "</think>" in t:
        t = t.split("</think>", 1)[1].strip()
    if t.startswith("```"):
        t = t.split("```", 2)
        t = t[1] if len(t) > 1 else text
        if t.startswith("json"):
            t = t[4:]
        t = t.strip().rstrip("`").strip()
    start = t.find("{")
    end = t.rfind("}")
    if start != -1 and end != -1 and end > start:
        return t[start : end + 1]
    return t
