"""Read-only endpoints for the eval dashboard."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.security import CurrentUser, get_current_user
from app.services.db import _client  # internal helper

router = APIRouter(prefix="/eval", tags=["eval"])


@router.get("/runs")
async def list_runs(
    _: Annotated[CurrentUser, Depends(get_current_user)],
    limit: int = 30,
):
    """Last N evaluation runs (powers the dashboard chart)."""
    try:
        res = (
            _client()
            .table("eval_runs")
            .select("*")
            .order("run_at", desc=True)
            .limit(min(max(limit, 1), 200))
            .execute()
        )
        return {"runs": list(reversed(res.data or []))}
    except Exception:
        return {"runs": []}


@router.get("/latest")
async def latest():
    try:
        res = (
            _client()
            .table("eval_runs")
            .select("*")
            .order("run_at", desc=True)
            .limit(1)
            .execute()
        )
        return (res.data or [None])[0]
    except Exception:
        return None
