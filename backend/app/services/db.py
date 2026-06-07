"""Supabase access for persistence (chat history, FIRs, investigations, cases).

The backend uses the SERVICE-ROLE key so it can write on behalf of authenticated
users. The browser never sees this key — it only talks to this backend.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any

from app.config import settings


@lru_cache
def _client():
    from supabase import create_client

    key = settings.supabase_service_key or settings.supabase_anon_key
    return create_client(settings.supabase_url, key)


# ---- user profiles / RBAC -----------------------------------------------

def get_user_role(user_id: str) -> str:
    """Fetch the user role from the profiles table."""
    try:
        res = _client().table("profiles").select("role").eq("id", user_id).single().execute()
        return res.data.get("role", "user") if res.data else "user"
    except Exception:
        return "user"


# ---- chat history -------------------------------------------------------

def save_message(
    session_id: str,
    user_id: str | None,
    role: str,
    message: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Persist one chat message. Silent no-op on any failure.

    Same rationale as fetch_history: this is called from inside the async
    SSE generator. Any raised exception would tear down the stream before
    the first event reaches the browser. Local mode without Supabase just
    skips persistence.
    """
    row: dict[str, Any] = {
        "session_id": session_id,
        "user_id": user_id,
        "role": role,
        "message": message,
    }
    if metadata is not None:
        row["metadata"] = metadata
    try:
        _client().table("chat_history").insert(row).execute()
    except Exception:
        pass


def fetch_history(session_id: str, limit: int = 12) -> list[dict[str, Any]]:
    """Read the last `limit` messages of a session, oldest-first.

    Returns [] on ANY failure (no Supabase configured, network blip, table
    missing, etc.). The assistant streaming endpoint reads history before
    yielding its first SSE event; if this function raised, the generator
    would die before sse-starlette could send the 200 OK headers and the
    browser would see a bare connection drop ("network error"), not an
    HTTP error. Failing soft here means the assistant just operates without
    history context, which is the right behaviour in soft-auth / no-Supabase
    local mode.
    """
    try:
        res = (
            _client()
            .table("chat_history")
            .select("*")
            .eq("session_id", session_id)
            .order("created_at", desc=False)
            .limit(limit)
            .execute()
        )
        return res.data or []
    except Exception:
        return []


# ---- FIR ----------------------------------------------------------------

def save_fir(record: dict[str, Any]) -> dict[str, Any]:
    res = _client().table("fir_records").insert(record).execute()
    return (res.data or [{}])[0]


def get_fir(record_id: str) -> dict[str, Any] | None:
    """Single-row fetch for status polling + approval callback."""
    res = _client().table("fir_records").select("*").eq("id", record_id).single().execute()
    return res.data


def update_fir_status(record_id: str, status: str) -> dict[str, Any]:
    """Update FIR row's status (used by n8n approval callback).

    Allowed transitions: draft → pending_approval → approved | rejected → filed
    """
    fields = {"status": status, "updated_at": "now()"}
    res = _client().table("fir_records").update(fields).eq("id", record_id).execute()
    return (res.data or [{}])[0]


def list_all_firs() -> list[dict[str, Any]]:
    """List all FIRs (for Admin oversight)."""
    res = _client().table("fir_records").select("*").order("created_at", desc=True).execute()
    return res.data or []


# ---- investigation ------------------------------------------------------

def save_investigation(record: dict[str, Any]) -> dict[str, Any]:
    res = _client().table("investigations").insert(record).execute()
    return (res.data or [{}])[0]


# ---- cases / trial ------------------------------------------------------

def create_case(record: dict[str, Any]) -> dict[str, Any]:
    res = _client().table("cases").insert(record).execute()
    return (res.data or [{}])[0]


def update_case(case_id: str, fields: dict[str, Any]) -> dict[str, Any]:
    res = _client().table("cases").update(fields).eq("id", case_id).execute()
    return (res.data or [{}])[0]


def get_case(case_id: str) -> dict[str, Any] | None:
    res = _client().table("cases").select("*").eq("id", case_id).single().execute()
    return res.data


def list_all_cases(*, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    """List cases (for Judges/Lawyers to view the pool). Paginated by default.

    Why paginated: a year of usage could mean tens of thousands of cases —
    unconditionally returning everything kills the dashboard. limit defaults
    to 50 (matching `list_user_cases`); callers may raise it via query param.
    """
    res = (
        _client()
        .table("cases")
        .select("*")
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    return res.data or []


def list_user_cases(user_id: str) -> list[dict[str, Any]]:
    """List cases created by a specific user."""
    res = _client().table("cases").select("*").eq("user_id", user_id).order("created_at", desc=True).limit(50).execute()
    return res.data or []


def assign_case(case_id: str, role: str, user_id: str) -> dict[str, Any]:
    """Assign a case to a lawyer or judge."""
    field = "assigned_lawyer" if role == "lawyer" else "assigned_judge"
    res = _client().table("cases").update({field: user_id}).eq("id", case_id).execute()
    return (res.data or [{}])[0]


def submit_human_verdict(case_id: str, verdict: dict[str, Any], status: str) -> dict[str, Any]:
    """Submit a judge's final verdict override/approval."""
    fields = {
        "human_verdict": verdict,
        "human_verdict_status": status,
        "status": "closed",
        "updated_at": "now()",
    }
    res = _client().table("cases").update(fields).eq("id", case_id).execute()
    return (res.data or [{}])[0]


# ---- judgments (one row per court level — preserves full appeal chain) --

def upsert_judgment(record: dict[str, Any]) -> dict[str, Any]:
    """Insert or replace a judgment for a (case_id, court_level) pair.

    The judgments table has a unique index on (case_id, court_level), so
    re-running a trial at the same level UPDATES instead of duplicating.
    """
    res = (
        _client()
        .table("judgments")
        .upsert(record, on_conflict="case_id,court_level")
        .execute()
    )
    return (res.data or [{}])[0]


def list_judgments(case_id: str) -> list[dict[str, Any]]:
    """All judgments for a case (used to render the appeal chain in TrialPage)."""
    res = (
        _client()
        .table("judgments")
        .select("*")
        .eq("case_id", case_id)
        .execute()
    )
    return res.data or []


# ---- evidence (file metadata; binaries live in Supabase Storage) --------

def create_evidence(record: dict[str, Any]) -> dict[str, Any]:
    """Insert one row tying a Supabase Storage path to an investigation/FIR/user."""
    res = _client().table("evidence").insert(record).execute()
    return (res.data or [{}])[0]


def list_evidence(
    *,
    investigation_id: str | None = None,
    fir_id: str | None = None,
    user_id: str | None = None,
) -> list[dict[str, Any]]:
    """Return evidence rows filtered by any combination of the three FKs."""
    q = _client().table("evidence").select("*")
    if investigation_id:
        q = q.eq("investigation_id", investigation_id)
    if fir_id:
        q = q.eq("fir_id", fir_id)
    if user_id:
        q = q.eq("user_id", user_id)
    res = q.order("uploaded_at", desc=True).execute()
    return res.data or []


def delete_evidence(evidence_id: str, user_id: str) -> None:
    """Delete one evidence row. The frontend separately removes the binary
    from Supabase Storage."""
    _client().table("evidence").delete().eq("id", evidence_id).eq("user_id", user_id).execute()
