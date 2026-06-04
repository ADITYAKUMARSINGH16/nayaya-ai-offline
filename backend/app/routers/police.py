"""Investigation route — JWT-aware."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.agents.police import run_investigation
from app.core.security import CurrentUser, get_current_user
from app.schemas.models import InvestigationRequest, InvestigationResponse

router = APIRouter(prefix="/investigation", tags=["police"])


@router.post("", response_model=InvestigationResponse)
async def investigate(
    req: InvestigationRequest,
    user: Annotated[CurrentUser, Depends(get_current_user)],
):
    try:
        payload = InvestigationRequest(**{**req.model_dump(by_alias=False), "user_id": user.id or req.user_id})
        return await run_investigation(payload)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Investigation failed: {exc}")
