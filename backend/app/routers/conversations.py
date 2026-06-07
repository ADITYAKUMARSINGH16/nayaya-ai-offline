"""Conversation history endpoints (Claude-style sidebar).

A *conversation* in our model is the set of `chat_history` rows that share a
single `session_id`. We don't have a separate `conversations` table — the
session_id is the key, and the conversation's title is derived from its first
user message.

In soft-auth mode (the Supabase JWT can't be verified locally because the
project signs with ES256) the JWT-derived `user.id` is None. We fall back to
an explicit `?user_id=` query parameter so the read path still works.
"""
from __future__ import annotations

from collections import OrderedDict
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.security import CurrentUser, get_current_user
from app.services.db import _client

router = APIRouter(prefix="/conversations", tags=["conversations"])

_TITLE_MAX = 80


def _resolve_user_id(user: CurrentUser, query_user_id: str | None) -> str | None:
    """Pick the user id from JWT first, then fall back to query param."""
    return user.id or query_user_id


def _make_title(text: str) -> str:
    text = (text or "").strip().replace("\n", " ")
    if len(text) <= _TITLE_MAX:
        return text
    return text[: _TITLE_MAX - 1].rstrip() + "…"


@router.get("")
async def list_conversations(
    user: Annotated[CurrentUser, Depends(get_current_user)],
    user_id: Annotated[str | None, Query(alias="user_id")] = None,
    category: str = "assistant",
    limit: int = 50,
):
    """Return the caller's recent conversations (one row per session_id).

    Filtering by category:
      - PRIMARY: read `metadata->>type` (set explicitly by every writer:
        "lawyer_analysis", "judge_analysis", "trial", or absent for assistant).
      - FALLBACK: legacy rows from before metadata.type was wired use the old
        session_id prefix rule (`lawyer_*`, `judge_*`, `trial_*`). Both paths
        return the same shape so the UI doesn't care which matched.
    """
    uid = _resolve_user_id(user, user_id)
    if not uid:
        return {"conversations": []}

    try:
        res = (
            _client()
            .table("chat_history")
            .select("session_id, role, message, created_at, metadata")
            .eq("user_id", uid)
            .order("created_at", desc=False)
            .limit(2000)
            .execute()
        )
    except Exception:
        return {"conversations": []}

    # Map each frontend category → the metadata.type value(s) that match.
    # 'assistant' is special — it's anything without an explicit type tag
    # (i.e. plain chat) AND not legacy-prefixed.
    _CATEGORY_TO_TYPE = {
        "lawyer": {"lawyer_analysis"},
        "judge":  {"judge_analysis"},
        "trial":  {"trial"},
    }
    expected_types = _CATEGORY_TO_TYPE.get(category)   # None → assistant

    def _matches(row: dict) -> bool:
        meta = row.get("metadata") or {}
        rtype = meta.get("type") if isinstance(meta, dict) else None
        sid = row["session_id"]
        if expected_types is not None:
            # Primary: metadata.type matches. Fallback: legacy session_id prefix.
            if rtype in expected_types:
                return True
            # Legacy fallback for rows written before metadata.type was set.
            return any(sid.startswith(f"{c}_") for c in expected_types
                       for c in ({"lawyer_analysis": "lawyer",
                                  "judge_analysis":  "judge",
                                  "trial":           "trial"}.get(c, c),))
        # category == "assistant" → no specific type AND not a legacy-tagged session
        if rtype in {"lawyer_analysis", "judge_analysis", "trial"}:
            return False
        return not (sid.startswith("lawyer_") or sid.startswith("judge_") or sid.startswith("trial_"))

    all_rows = res.data or []
    rows = [r for r in all_rows if _matches(r)]

    by_session: "OrderedDict[str, dict]" = OrderedDict()
    for r in rows:
        sid = r["session_id"]
        if sid not in by_session:
            by_session[sid] = {
                "session_id": sid,
                "title": None,
                "first_at": r["created_at"],
                "last_at": r["created_at"],
                "message_count": 0,
            }
        conv = by_session[sid]
        conv["message_count"] += 1
        conv["last_at"] = r["created_at"]
        if conv["title"] is None and r["role"] == "user":
            conv["title"] = _make_title(r["message"])

    conversations = sorted(by_session.values(), key=lambda c: c["last_at"], reverse=True)
    for c in conversations:
        if not c["title"]:
            c["title"] = "New conversation"
    return {"conversations": conversations[:limit]}


@router.get("/{session_id}/messages")
async def get_messages(
    session_id: str,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    user_id: Annotated[str | None, Query(alias="user_id")] = None,
):
    uid = _resolve_user_id(user, user_id)
    if not uid:
        raise HTTPException(status_code=401, detail="Sign-in required")
    try:
        res = (
            _client()
            .table("chat_history")
            .select("role, message, created_at, metadata")
            .eq("user_id", uid)
            .eq("session_id", session_id)
            .order("created_at", desc=False)
            .execute()
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"DB error: {exc}")
    return {"session_id": session_id, "messages": res.data or []}


@router.delete("/{session_id}")
async def delete_conversation(
    session_id: str,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    user_id: Annotated[str | None, Query(alias="user_id")] = None,
):
    uid = _resolve_user_id(user, user_id)
    if not uid:
        raise HTTPException(status_code=401, detail="Sign-in required")
    try:
        _client().table("chat_history").delete().eq("user_id", uid).eq(
            "session_id", session_id
        ).execute()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"DB error: {exc}")
    return {"ok": True}
