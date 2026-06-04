"""Deterministic act+section lookup.

The 4-tier router's bottom two tiers. For citation-style queries ("BNS 202",
"section 303") we should never run vector search — the answer is a dictionary
lookup against `sections_enriched.json`.

Tier 1: `lookup_direct(act, number)`  → exact act + section match.
Tier 2: `lookup_by_number(number, acts)` → same number across the act subset
        the router suggests (e.g. ["BNS","BNSS"]).

The enriched JSON is loaded once at module import and cached in-memory
(~3 MB). Same shape the ingest pipeline emits.
"""
from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _default_enriched_path() -> Path:
    """Locate sections_enriched.json on dev (`./data/`) or container (`/app/data/`)."""
    candidates = [
        _BACKEND_ROOT / "data" / "sections_enriched.json",
        _BACKEND_ROOT.parent / "data" / "sections_enriched.json",
        Path("/app/data/sections_enriched.json"),
        Path("data/sections_enriched.json"),
    ]
    override = os.environ.get("SECTIONS_ENRICHED_PATH")
    if override:
        candidates.insert(0, Path(override))
    for p in candidates:
        if p.exists():
            return p
    return candidates[0]   # return a path even if missing, so error is loud


@lru_cache(maxsize=1)
def _load_index() -> dict[tuple[str, str], dict[str, Any]]:
    """Return {(ACT_UPPER, NUMBER_STR): section_record}."""
    path = _default_enriched_path()
    if not path.exists():
        log.warning("section_lookup: sections_enriched.json not found at %s", path)
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            records = json.load(f)
    except Exception as exc:
        log.warning("section_lookup: failed to load %s: %s", path, exc)
        return {}

    index: dict[tuple[str, str], dict[str, Any]] = {}
    for rec in records:
        act = str(rec.get("act") or "").strip().upper()
        num = str(rec.get("number") or "").strip()
        if not act or not num:
            continue
        index[(act, num)] = rec
    log.info("section_lookup: indexed %d sections from %s", len(index), path)
    return index


def _to_citation(rec: dict[str, Any]) -> dict[str, Any]:
    """Convert an enriched record to the citation shape rag.py emits."""
    title = rec.get("title_clean") or rec.get("raw_title") or ""
    body = rec.get("raw_body") or ""
    summary = rec.get("summary") or ""
    text = (body or summary).strip()
    return {
        "score": 1.0,                      # exact lookup → max confidence
        "act": rec.get("act", ""),
        "category": "",
        "section_number": str(rec.get("number", "")),
        "section_title": title,
        "text": text,
        "summary": summary,
        "punishment": rec.get("punishment"),
    }


def get_metadata(act: str, number: str | int) -> dict[str, Any] | None:
    """Lightweight lookup that returns the enriched metadata fields without
    materialising a citation record. Used by rag.py to augment Pinecone
    results with structured fields (summary, punishment) that aren't stored
    in Pinecone metadata.
    """
    if not act or number is None:
        return None
    key = (str(act).strip().upper(), str(number).strip())
    rec = _load_index().get(key)
    if not rec:
        return None
    return {
        "summary":    rec.get("summary") or "",
        "punishment": rec.get("punishment"),
        "title_clean": rec.get("title_clean") or "",
    }


def lookup_direct(act: str, number: str | int) -> dict[str, Any] | None:
    """Tier 1: explicit act + section. Returns a citation-shaped dict or None."""
    if not act or number is None:
        return None
    key = (str(act).strip().upper(), str(number).strip())
    rec = _load_index().get(key)
    return _to_citation(rec) if rec else None


def lookup_by_number(
    number: str | int,
    acts: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Tier 2: bare section number, optionally narrowed by act subset.

    Returns a list of citation-shaped dicts (one per matching act).
    """
    if number is None:
        return []
    num = str(number).strip()
    act_subset = {a.strip().upper() for a in (acts or [])} or {"BNS", "BNSS", "BSA"}
    out: list[dict[str, Any]] = []
    idx = _load_index()
    for (act, n), rec in idx.items():
        if n == num and act in act_subset:
            out.append(_to_citation(rec))
    out.sort(key=lambda r: ["BNS", "BNSS", "BSA"].index(r["act"]) if r["act"] in ("BNS", "BNSS", "BSA") else 99)
    return out


def is_loaded() -> bool:
    return bool(_load_index())


def get_all_acts() -> list[str]:
    """Return a list of all acts available in the index."""
    idx = _load_index()
    return sorted(list(set(act for act, _ in idx.keys())))


def get_sections_by_act(act: str) -> list[dict[str, Any]]:
    """Return all sections for a specific act."""
    if not act:
        return []
    idx = _load_index()
    act = act.strip().upper()
    sections = [rec for (a, n), rec in idx.items() if a == act]
    
    def sort_key(rec):
        n = str(rec.get("number", "")).strip()
        import re
        match = re.match(r"^(\d+)", n)
        return int(match.group(1)) if match else 999999
        
    sections.sort(key=sort_key)
    # Convert to citation format for consistency with frontend expectations
    return [_to_citation(rec) for rec in sections]


def search_sections(query: str, acts: list[str] | None = None) -> list[dict[str, Any]]:
    """Simple text search across all sections."""
    if not query:
        return []
    idx = _load_index()
    q = query.lower()
    act_subset = {a.strip().upper() for a in (acts or [])} if acts else None
    
    results = []
    for (a, n), rec in idx.items():
        if act_subset and a not in act_subset:
            continue
            
        title = (rec.get("title_clean") or rec.get("raw_title") or "").lower()
        body = (rec.get("raw_body") or rec.get("summary") or "").lower()
        
        if q in title or q in body or q == n.lower():
            results.append(_to_citation(rec))
            
    # Sort results to prefer title matches or exact section number matches
    def match_score(rec):
        n_val = str(rec.get("section_number", "")).lower()
        t_val = str(rec.get("section_title", "")).lower()
        if q == n_val:
            return 0
        if q in t_val:
            return 1
        return 2
        
    results.sort(key=match_score)
    return results
