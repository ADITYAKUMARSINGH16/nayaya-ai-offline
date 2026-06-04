"""Provider for any OpenAI-compatible chat API (OpenAI and Groq both qualify).

Note on GPT-5 / o-series quirks (OpenAI only):
- They reject `max_tokens` — must use `max_completion_tokens` instead.
- They reject any non-default `temperature` (only 1.0 is allowed).
- Otherwise the schema is identical, so we just detect the model prefix and
  translate the payload.
"""
from __future__ import annotations

import json
from typing import AsyncIterator

import httpx

from .base import LLMProvider


def _is_reasoning_model(model: str) -> bool:
    """GPT-5 family and o-series have stricter parameter requirements."""
    m = (model or "").lower()
    return m.startswith(("gpt-5", "o1", "o3", "o4"))


# Reasoning models silently consume `max_completion_tokens` on internal reasoning
# before emitting any visible content. Anything below this floor (e.g. our
# 5-token classifier ask) yields an empty string. We set this high so neither
# small (classifier) nor large (FIR draft, full judgment) outputs ever get
# truncated.
_REASONING_TOKEN_FLOOR = 8000


def _build_payload(
    *,
    model: str,
    messages: list[dict[str, str]],
    temperature: float,
    max_tokens: int,
    json_mode: bool = False,
    stream: bool = False,
) -> dict:
    payload: dict = {"model": model, "messages": messages}
    if _is_reasoning_model(model):
        # GPT-5 / o-series: max_completion_tokens, no custom temperature,
        # and force minimal reasoning so short classifier/verifier calls don't
        # burn the entire budget on hidden reasoning tokens.
        payload["max_completion_tokens"] = max(max_tokens, _REASONING_TOKEN_FLOOR)
        payload["reasoning_effort"] = "minimal"
    else:
        payload["max_tokens"] = max_tokens
        payload["temperature"] = temperature
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    if stream:
        payload["stream"] = True
    return payload


class OpenAICompatibleProvider(LLMProvider):
    def __init__(
        self,
        *,
        name: str,
        api_key: str,
        base_url: str,
        model: str,
        fast_model: str | None = None,
        timeout: float = 90.0,
    ):
        self.name = name
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._fast_model = fast_model or model
        self._timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.3,
        max_tokens: int = 1024,
        fast: bool = False,
        json_mode: bool = False,
    ) -> str:
        model = self._fast_model if fast else self._model
        payload = _build_payload(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=json_mode,
        )
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                f"{self._base_url}/chat/completions",
                json=payload,
                headers=self._headers(),
            )
            if resp.status_code >= 400:
                # Surface OpenAI's actual error message so the upstream router can show it.
                raise httpx.HTTPStatusError(
                    f"{resp.status_code} {resp.text}", request=resp.request, response=resp,
                )
            data = resp.json()
        return data["choices"][0]["message"]["content"] or ""

    async def stream(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.3,
        max_tokens: int = 1024,
        fast: bool = False,
    ) -> AsyncIterator[str]:
        """Yield token deltas from the OpenAI-compatible SSE stream."""
        model = self._fast_model if fast else self._model
        payload = _build_payload(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            async with client.stream(
                "POST",
                f"{self._base_url}/chat/completions",
                json=payload,
                headers=self._headers(),
            ) as resp:
                if resp.status_code >= 400:
                    body = await resp.aread()
                    raise httpx.HTTPStatusError(
                        f"{resp.status_code} {body.decode(errors='ignore')}",
                        request=resp.request,
                        response=resp,
                    )
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    chunk = line[5:].strip()
                    if chunk == "[DONE]":
                        break
                    try:
                        parsed = json.loads(chunk)
                        delta = (parsed.get("choices") or [{}])[0].get("delta", {}).get("content")
                        if delta:
                            yield delta
                    except json.JSONDecodeError:
                        continue
