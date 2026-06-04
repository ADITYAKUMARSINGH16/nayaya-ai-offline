"""Admin endpoints (graph rebuild, eval trigger, stats).

Two ways to authenticate:

1. An *admin* JWT (caller's email is in `ADMIN_EMAILS`).
2. An `X-Internal-Key` header matching `ADMIN_INTERNAL_KEY` (used by n8n
   cron workflows running inside the docker network).
"""
from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException

from app.config import settings
from app.core.security import CurrentUser, get_current_user
from app.services.legal_graph import graph_stats

router = APIRouter(prefix="/admin", tags=["admin"])


def _require_admin_or_internal(
    user: Annotated[CurrentUser, Depends(get_current_user)],
    x_internal_key: Annotated[str | None, Header()] = None,
) -> CurrentUser:
    if x_internal_key and settings.admin_internal_key and x_internal_key == settings.admin_internal_key:
        return CurrentUser(id="internal", email="internal", is_admin=True, is_anonymous=False)
    if user.is_anonymous or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")
    return user


@router.get("/stats")
async def stats(_: Annotated[CurrentUser, Depends(_require_admin_or_internal)]):
    return {"graph": graph_stats()}


# Backend root — /app in Docker, the actual repo dir on Render.
# Using __file__ so we don't hardcode a Docker-only path.
_BACKEND_ROOT = str(Path(__file__).resolve().parents[2])


@router.post("/rebuild-graph")
async def rebuild_graph(_: Annotated[CurrentUser, Depends(_require_admin_or_internal)]):
    """Re-run scripts/build_graph.py to refresh the legal graph JSON."""
    try:
        proc = await asyncio.to_thread(
            subprocess.run,
            [sys.executable, "-m", "scripts.build_graph"],
            cwd=_BACKEND_ROOT,
            capture_output=True,
            text=True,
            timeout=600,
        )
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"rebuild failed: {exc}")

    if proc.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail=f"build_graph exited {proc.returncode}: {proc.stderr.strip()[-400:]}",
        )
    return {
        "ok": True,
        "stdout": proc.stdout.strip().splitlines()[-10:],
        "graph": graph_stats(),
    }


@router.post("/run-eval")
async def run_eval(_: Annotated[CurrentUser, Depends(_require_admin_or_internal)]):
    """Trigger the labeled-eval runner. Results land in Supabase `eval_runs`."""
    try:
        proc = await asyncio.to_thread(
            subprocess.run,
            [sys.executable, "-m", "eval.runner"],
            cwd=_BACKEND_ROOT,
            capture_output=True,
            text=True,
            timeout=900,
        )
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"eval failed: {exc}")
    if proc.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail=f"runner exited {proc.returncode}: {proc.stderr.strip()[-400:]}",
        )
    return {"ok": True, "stdout": proc.stdout.strip().splitlines()[-30:]}
