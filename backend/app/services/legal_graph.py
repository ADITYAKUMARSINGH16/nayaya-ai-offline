"""LegalGraph-Lite — a cheap, no-Neo4j knowledge graph over BNS/BNSS/BSA sections.

We build an adjacency dict `{section_number: [neighbour section numbers]}` from
two free signals already in our corpus:

1. **Regex cross-references** in the section text (e.g. "as defined in section
   103", "subject to section 51"). Pure regex → $0 cost.
2. **Metadata co-membership** (same act + same category) → already in Pinecone
   metadata, just unused before.

Persisted to `data/legal_graph.json` (mounted volume) so the FastAPI process
can hot-load it without re-hitting Pinecone.
"""
from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from app.config import settings

# Cross-reference patterns commonly seen in Indian statutes.
_REF_PATTERNS = [
    re.compile(r"\bsection[s]?\s*(\d{1,3})", re.IGNORECASE),
    re.compile(r"\bsec\.?\s*(\d{1,3})", re.IGNORECASE),
    re.compile(r"\bunder\s+(?:section|sec)\s*(\d{1,3})", re.IGNORECASE),
    re.compile(r"\bas\s+defined\s+in\s+(?:section|sec)?\s*(\d{1,3})", re.IGNORECASE),
    re.compile(r"\bsubject\s+to\s+(?:section|sec)?\s*(\d{1,3})", re.IGNORECASE),
]

def _default_graph_path() -> Path:
    """Auto-detect a writable location for the legal graph JSON.

    Docker (compose): /app/data/legal_graph.json (the bind-mounted volume).
    Render / generic: backend/data/legal_graph.json (relative to this module's
                       repo root, since /app doesn't exist on Render).
    """
    if Path("/app/data").exists() or Path("/app").exists():
        return Path("/app/data/legal_graph.json")
    backend_root = Path(__file__).resolve().parents[2]
    return backend_root / "data" / "legal_graph.json"


GRAPH_PATH = Path(os.getenv("LEGAL_GRAPH_PATH") or str(_default_graph_path()))


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def extract_references(text: str, *, self_number: str | None = None) -> set[str]:
    """Pull every section-number reference out of a block of statute text."""
    refs: set[str] = set()
    if not text:
        return refs
    for pat in _REF_PATTERNS:
        for m in pat.finditer(text):
            refs.add(m.group(1))
    if self_number and self_number in refs:
        refs.discard(self_number)  # no self-loops
    return refs


def build_adjacency(sections: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Turn a stream of section dicts into the persisted graph structure.

    Each `section` dict must have: section_number, section_title, act, category, text.
    Optional: `cross_references` (list of {act, section}) — if present, these
    structured edges are TRUSTED ABOVE the regex extractor (they came from the
    GPT-5-nano enrichment pass and are much higher precision).

    Returns:
        {
          "sections": { "303": {"title": ..., "act": ..., "category": ...}, ... },
          "edges":    { "303": ["305", "318"], ... }
        }
    """
    by_number: dict[str, dict[str, Any]] = {}
    edges: dict[str, set[str]] = defaultdict(set)

    for s in sections:
        num = str(s.get("section_number") or "").strip()
        if not num:
            continue
        by_number[num] = {
            "title":    s.get("section_title", ""),
            "act":      s.get("act", ""),
            "category": s.get("category", ""),
        }
        # Prefer structured cross-references from enrichment (high precision).
        structured = s.get("cross_references") or []
        if structured:
            for ref in structured:
                rnum = str(ref.get("section") or "").strip()
                if rnum and rnum != num:
                    edges[num].add(rnum)
                    edges[rnum].add(num)
        else:
            # Fallback: regex over raw text.
            for ref in extract_references(s.get("text", ""), self_number=num):
                edges[num].add(ref)
                edges[ref].add(num)

    # Metadata co-membership edges (same act+category) — only for small buckets.
    by_bucket: dict[tuple[str, str], list[str]] = defaultdict(list)
    for num, meta in by_number.items():
        by_bucket[(meta["act"], meta["category"])].append(num)
    for bucket, members in by_bucket.items():
        if 2 <= len(members) <= 12:
            for a in members:
                for b in members:
                    if a != b:
                        edges[a].add(b)

    cleaned_edges = {
        n: sorted(ns & set(by_number.keys()))
        for n, ns in edges.items()
        if n in by_number
    }
    return {"sections": by_number, "edges": cleaned_edges}


def save_graph(graph: dict[str, Any], path: Path = GRAPH_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(graph, indent=2, ensure_ascii=False))
    # invalidate the in-process cache so the next read sees fresh data.
    load_graph.cache_clear()


# ---------------------------------------------------------------------------
# Load + query
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def load_graph(path: Path = GRAPH_PATH) -> dict[str, Any]:
    """Return the persisted graph, or an empty stub if it hasn't been built yet."""
    p = Path(path)
    if not p.exists():
        return {"sections": {}, "edges": {}}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {"sections": {}, "edges": {}}


def neighbours(section_number: str, *, hops: int = 1) -> list[str]:
    """Walk `hops` edges out from `section_number`."""
    g = load_graph()
    edges: dict[str, list[str]] = g.get("edges", {})
    if section_number not in edges:
        return []

    seen: set[str] = {section_number}
    frontier: set[str] = {section_number}
    for _ in range(max(1, hops)):
        nxt: set[str] = set()
        for n in frontier:
            for nb in edges.get(n, []):
                if nb not in seen:
                    nxt.add(nb)
                    seen.add(nb)
        frontier = nxt
        if not frontier:
            break
    seen.discard(section_number)
    return sorted(seen)


def expand_seed_sections(section_numbers: Iterable[str], *, hops: int = 1) -> list[str]:
    """Expand a list of seed sections to include their 1-hop (or N-hop) neighbours."""
    out: set[str] = set()
    for n in section_numbers:
        out.update(neighbours(n, hops=hops))
    return sorted(out - set(section_numbers))


def graph_stats() -> dict[str, int]:
    g = load_graph()
    edges: dict[str, list[str]] = g.get("edges", {})
    return {
        "sections": len(g.get("sections", {})),
        "edges": sum(len(v) for v in edges.values()) // 2,  # undirected
        "graph_loaded": int(GRAPH_PATH.exists()),
    }
