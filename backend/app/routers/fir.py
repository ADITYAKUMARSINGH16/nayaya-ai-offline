import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.agents.fir import run_fir
from app.config import settings
from app.core.security import CurrentUser, get_current_user
from app.schemas.models import FIRRequest, FIRResponse
from app.services import db
from app.services.n8n import request_fir_approval

router = APIRouter(prefix="/fir", tags=["fir"])


@router.post("", response_model=FIRResponse)
async def generate_fir(
    req: FIRRequest,
    user: Annotated[CurrentUser, Depends(get_current_user)],
):
    try:
        result = await run_fir(req.model_copy(update={"user_id": user.id or req.user_id}))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"FIR generation failed: {exc}")

    # Optional handoff to n8n for human approval before the draft is treated as final.
    # When enabled:
    #   1. Flip the FIR's DB status to "pending_approval" so the frontend's
    #      polling endpoint (/api/fir/{id}/status) reflects the workflow state.
    #   2. Fire the n8n webhook in the background — the workflow blocks on a
    #      Wait node until a human clicks Approve/Reject on Telegram, then
    #      callbacks /api/internal/fir/{id}/approval to flip status again.
    if settings.n8n_fir_approval and result.record_id:
        try:
            db.update_fir_status(result.record_id, "pending_approval")
        except Exception:
            pass   # status update isn't fatal — the n8n callback will retry
        # Fire-and-forget — the user gets their FIR back immediately while
        # the workflow runs in the background.
        asyncio.create_task(request_fir_approval({
            "record_id":        result.record_id,
            "user_id":          user.id or req.user_id,
            "user_email":       user.email,
            "complainant_name": req.complainant_name,
            "incident_date":    str(req.incident_date),
            "fir_text":         result.fir_text,
        }))

    return result
