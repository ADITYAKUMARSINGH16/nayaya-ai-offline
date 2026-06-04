"""Thin async client for posting to n8n webhooks.

The backend is the integration source-of-truth — n8n receives events and fans
them out (notifications, approvals, audit). Failures here must never break the
primary user-facing request, so every call is fire-and-forget with a soft error.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import settings

log = logging.getLogger("nyaya.n8n")


async def post_event(path: str, payload: dict[str, Any], *, timeout: float = 8.0) -> bool:
    """POST `payload` to `<N8N_WEBHOOK_BASE>/<path>`. Returns True on 2xx, else False."""
    url = f"{settings.n8n_webhook_base.rstrip('/')}/{path.lstrip('/')}"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(url, json=payload)
            ok = 200 <= r.status_code < 300
            if not ok:
                log.warning("n8n %s returned %s: %s", path, r.status_code, r.text[:200])
            return ok
    except Exception as exc:  # noqa: BLE001
        log.warning("n8n %s failed: %s", path, exc)
        return False


async def notify_verdict(case: dict[str, Any]) -> bool:
    """Fire the verdict fan-out webhook (Email/Slack/Telegram/WhatsApp)."""
    if not settings.n8n_notify_on_verdict:
        return False
    return await post_event(
        "case-notify",
        {
            "case_id":              case.get("case_id"),
            "court_level":          case.get("court_level"),
            "final_judgment":       case.get("final_judgment"),
            "applicable_sections":  case.get("applicable_sections", []),
            "user_email":           case.get("user_email"),
        },
    )


async def request_fir_approval(payload: dict[str, Any]) -> bool:
    """Hand a drafted FIR to n8n's human-approval workflow.

    n8n holds the request open (Wait node) until a human approves; the
    callback into the backend persists the FIR. Returns True if the workflow
    accepted the handoff.
    """
    return await post_event("fir-approve", payload)
