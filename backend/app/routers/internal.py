"""Internal callback endpoints — called by n8n workflows, not the frontend.

Auth: shared-secret header `X-Internal-Key` matching env `ADMIN_INTERNAL_KEY`
(or the legacy `INTERNAL_CALLBACK_KEY`).

Endpoints:
  PATCH /api/internal/fir/{record_id}/approval
      body: {"status": "approved" | "rejected", "reviewer": "string"}
      response: {"ok": true, "fir": {...}}

  GET /api/fir/{record_id}/status  (user-facing polling)

  GET /api/fir/{record_id}/decide?status=approved&key=...
      Direct-click endpoint hit by the reviewer's Telegram button. Validates
      `key` query param against ADMIN_INTERNAL_KEY, flips the FIR status,
      returns an HTML page the reviewer sees in their browser.
"""
from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.services import db


internal_router = APIRouter(prefix="/internal", tags=["internal"])

# Separate router so the public status endpoint lives at /api/fir/... not /api/internal/...
fir_status_router = APIRouter(prefix="/fir", tags=["fir"])


class ApprovalCallback(BaseModel):
    status: str          # "approved" | "rejected"
    reviewer: str = ""   # display name / identifier of the human who decided


def _verify_internal_key(provided: str | None) -> None:
    # Accept either ADMIN_INTERNAL_KEY (user's existing env var, reused) or
    # INTERNAL_CALLBACK_KEY (forward-compat name). Whichever is set will work.
    expected = (
        os.environ.get("ADMIN_INTERNAL_KEY")
        or os.environ.get("INTERNAL_CALLBACK_KEY")
        or ""
    )
    if not expected:
        # Misconfigured backend — fail loudly rather than accept anyone
        raise HTTPException(status_code=503,
                            detail="ADMIN_INTERNAL_KEY (or INTERNAL_CALLBACK_KEY) not configured on server")
    if not provided or provided != expected:
        raise HTTPException(status_code=401, detail="invalid internal key")


@internal_router.patch("/fir/{record_id}/approval")
async def fir_approval_callback(
    record_id: str,
    body: ApprovalCallback,
    x_internal_key: str | None = Header(default=None, alias="X-Internal-Key"),
) -> dict[str, Any]:
    """n8n calls this after a reviewer approves/rejects an FIR in Telegram.

    Idempotency: if the FIR is already in a terminal state (approved | rejected
    | filed), we return 200 with `already=True` instead of PATCHing again.
    This prevents the dual-path approval flow (Wait-node resume + Telegram
    inline button) from clobbering each other when Telegram retries delivery.
    """
    _verify_internal_key(x_internal_key)

    new_status = body.status.strip().lower()
    if new_status not in {"approved", "rejected"}:
        raise HTTPException(status_code=400,
                            detail=f"status must be approved|rejected, got {body.status!r}")

    # Idempotency check — read first, only update if mutable.
    try:
        existing = db.get_fir(record_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"DB fetch failed: {exc}")
    if not existing:
        raise HTTPException(status_code=404, detail=f"FIR {record_id} not found")

    cur = (existing.get("status") or "").lower()
    if cur in {"approved", "rejected", "filed"}:
        return {"ok": True, "fir": existing, "reviewer": body.reviewer,
                "already": True, "previous_status": cur}

    try:
        updated = db.update_fir_status(record_id, new_status)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"DB update failed: {exc}")

    if not updated:
        raise HTTPException(status_code=404, detail=f"FIR {record_id} not found")

    return {"ok": True, "fir": updated, "reviewer": body.reviewer, "already": False}


@fir_status_router.get("/{record_id}/status")
async def fir_status(record_id: str) -> dict[str, Any]:
    """Public polling endpoint — frontend polls this after submitting an FIR
    to see when approval lands."""
    try:
        rec = db.get_fir(record_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"DB fetch failed: {exc}")
    if not rec:
        raise HTTPException(status_code=404, detail=f"FIR {record_id} not found")
    return {
        "id":     rec.get("id"),
        "status": rec.get("status"),
        "updated_at": rec.get("updated_at"),
    }


def _confirmation_html(record_id: str, decision: str, ok: bool) -> str:
    """Simple HTML the reviewer sees after clicking a button in Telegram."""
    color = "#10b981" if decision == "approved" and ok else (
        "#ef4444" if decision == "rejected" and ok else "#6b7280"
    )
    icon = "✅" if decision == "approved" and ok else (
        "❌" if decision == "rejected" and ok else "⚠️"
    )
    title = f"FIR {decision.capitalize()}" if ok else "Action Failed"
    body = (
        f"FIR <code>{record_id}</code> has been marked <strong>{decision}</strong>."
        if ok else
        "The decision could not be recorded. Please contact the system administrator."
    )
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{title}</title>
<style>
  body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
       background:#f9fafb;display:flex;align-items:center;justify-content:center;
       min-height:100vh;margin:0;color:#111827}}
  .card{{background:white;border-radius:12px;padding:48px;text-align:center;
        box-shadow:0 4px 24px rgba(0,0,0,0.06);max-width:420px}}
  .icon{{font-size:64px;margin-bottom:16px}}
  h1{{color:{color};margin:0 0 8px 0;font-size:28px}}
  p{{color:#6b7280;line-height:1.5;font-size:15px}}
  code{{background:#f3f4f6;padding:2px 6px;border-radius:4px;font-size:13px}}
</style></head>
<body><div class="card">
  <div class="icon">{icon}</div>
  <h1>{title}</h1>
  <p>{body}</p>
</div></body></html>"""


@fir_status_router.get("/{record_id}/decide")
async def fir_decide(
    record_id: str,
    status: str = Query(..., description="approved | rejected"),
    key: str = Query(..., description="shared secret matching ADMIN_INTERNAL_KEY"),
) -> HTMLResponse:
    """Direct-click endpoint hit by the reviewer's Telegram button.

    URL pattern (built by n8n workflow):
      /api/fir/{record_id}/decide?status=approved&key=<ADMIN_INTERNAL_KEY>

    Returns an HTML confirmation page (since this is opened in a browser).
    """
    expected = (os.environ.get("ADMIN_INTERNAL_KEY")
                or os.environ.get("INTERNAL_CALLBACK_KEY") or "")
    if not expected or key != expected:
        return HTMLResponse(_confirmation_html(record_id, status, ok=False),
                             status_code=401)

    status_norm = status.strip().lower()
    if status_norm not in {"approved", "rejected"}:
        return HTMLResponse(_confirmation_html(record_id, status, ok=False),
                             status_code=400)

    try:
        db.update_fir_status(record_id, status_norm)
    except Exception:
        return HTMLResponse(_confirmation_html(record_id, status_norm, ok=False),
                             status_code=502)

    return HTMLResponse(_confirmation_html(record_id, status_norm, ok=True))
