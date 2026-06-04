from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.agents.courtroom import run_trial
from app.core.security import CurrentUser, get_current_user
from app.schemas.models import TrialRequest, TrialResponse
from app.services import db
from app.services.n8n import notify_verdict

router = APIRouter(prefix="/cases", tags=["cases"])


@router.get("")
async def list_cases(
    user: Annotated[CurrentUser, Depends(get_current_user)],
):
    if user.role in ("judge", "admin", "lawyer"):
        return db.list_all_cases()
    return db.list_user_cases(user.id)


@router.post("/trial", response_model=TrialResponse)
async def trial(
    req: TrialRequest,
    user: Annotated[CurrentUser, Depends(get_current_user)],
):
    try:
        result = await run_trial(req.model_copy(update={"user_id": user.id or req.user_id}))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Trial simulation failed: {exc}")

    # Best-effort fire-and-forget notification (Email/Slack/Telegram via n8n).
    await notify_verdict({
        "case_id":             result.case_id,
        "court_level":         result.court_level,
        "final_judgment":      result.judgment.final_judgment,
        "applicable_sections": result.judgment.applicable_sections,
        "user_email":          user.email,
    })

    return result


@router.get("/{case_id}")
async def get_case(case_id: str):
    case = db.get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    return case
