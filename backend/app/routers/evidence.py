"""Evidence file metadata endpoints.

The actual binary lives in Supabase Storage (`evidence` bucket) — the frontend
uploads directly to Supabase. We only persist the metadata row that ties the
storage path back to an investigation / FIR / user.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.core.security import CurrentUser, get_current_user
from app.services import db

router = APIRouter(prefix="/evidence", tags=["evidence"])


class EvidenceIn(BaseModel):
    investigation_id: str | None = None
    fir_id: str | None = None
    user_id: str | None = None             # fallback when JWT verification is soft
    storage_path: str
    filename: str
    mime_type: str | None = None
    size_bytes: int | None = None
    description: str | None = None


@router.post("")
async def create(
    body: EvidenceIn,
    user: Annotated[CurrentUser, Depends(get_current_user)],
):
    uid = user.id or body.user_id
    if not uid:
        raise HTTPException(status_code=401, detail="Sign-in required")
    try:
        row = db.create_evidence({
            "investigation_id": body.investigation_id,
            "fir_id":           body.fir_id,
            "user_id":          uid,
            "storage_path":     body.storage_path,
            "filename":         body.filename,
            "mime_type":        body.mime_type,
            "size_bytes":       body.size_bytes,
            "description":      body.description,
        })
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"DB error: {exc}")
    return row


@router.get("")
async def list_(
    user: Annotated[CurrentUser, Depends(get_current_user)],
    investigation_id: Annotated[str | None, Query()] = None,
    fir_id: Annotated[str | None, Query()] = None,
    user_id: Annotated[str | None, Query()] = None,
):
    uid = user.id or user_id
    if not uid:
        return {"evidence": []}
    try:
        rows = db.list_evidence(
            investigation_id=investigation_id,
            fir_id=fir_id,
            user_id=uid,
        )
    except Exception:
        rows = []
    return {"evidence": rows}


@router.delete("/{evidence_id}")
async def delete(
    evidence_id: str,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    user_id: Annotated[str | None, Query()] = None,
):
    uid = user.id or user_id
    if not uid:
        raise HTTPException(status_code=401, detail="Sign-in required")
    try:
        db.delete_evidence(evidence_id, uid)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"DB error: {exc}")
    return {"ok": True}
