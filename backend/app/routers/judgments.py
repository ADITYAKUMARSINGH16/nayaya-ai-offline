"""Judgment history endpoints (one row per court level — full appeal chain)."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.security import CurrentUser, get_current_user
from app.services import db

router = APIRouter(prefix="/cases", tags=["judgments"])


@router.get("/{case_id}/judgments")
async def list_judgments_for_case(
    case_id: str,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    user_id: Annotated[str | None, Query()] = None,
):
    """All judgments for a case, ordered by court level (district → high → supreme)."""
    if not (user.id or user_id):
        raise HTTPException(status_code=401, detail="Sign-in required")
    try:
        rows = db.list_judgments(case_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"DB error: {exc}")
    # Stable display order regardless of insertion time
    order = {"district": 0, "high": 1, "supreme": 2}
    rows.sort(key=lambda r: order.get(r.get("court_level"), 99))
    return {"case_id": case_id, "judgments": rows}
