"""Build LegalGraph-Lite from the enriched JSON (preferred) or Pinecone.

Preference order:
  1. data/sections_enriched.json  — has structured cross_references from the
     GPT-5-nano enrichment pass. Higher precision than regex.
  2. Pinecone metadata scan — fallback. Dedupes by section_number because the
     enriched ingest emits ~6 vectors per section.

Usage (from inside the backend container):
    python -m scripts.build_graph
    python -m scripts.build_graph --enriched /app/data/sections_enriched.json
Or invoked by the n8n cron via the /api/admin/rebuild-graph endpoint.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402
from app.services.legal_graph import GRAPH_PATH, build_adjacency, save_graph  # noqa: E402


PAGE_SIZE = 100


def _default_enriched_path() -> Path:
    """Auto-detect where sections_enriched.json lives.

    Docker: /app/data/sections_enriched.json (bind mount).
    Render / generic: backend/data/sections_enriched.json (relative to script).
    """
    if Path("/app/data").exists():
        return Path("/app/data/sections_enriched.json")
    return Path(__file__).resolve().parents[1] / "data" / "sections_enriched.json"


DEFAULT_ENRICHED = _default_enriched_path()


def load_from_enriched(path: Path) -> list[dict[str, Any]]:
    """Read the enriched JSON and shape it for build_adjacency()."""
    data = json.loads(path.read_text())
    out: list[dict[str, Any]] = []
    for r in data:
        out.append({
            "section_number":   str(r.get("number", "")).strip(),
            "section_title":    r.get("title_clean") or r.get("raw_title", ""),
            "act":              r.get("act", ""),
            "category":         "",
            "text":             r.get("raw_body", ""),
            "cross_references": r.get("cross_references") or [],
        })
    return out


def iter_all_sections() -> list[dict[str, Any]]:
    """Pinecone-scan fallback. Dedupes — enriched ingest writes 6 vectors per section."""
    from pinecone import Pinecone

    kwargs = {"api_key": settings.pinecone_api_key}
    if settings.pinecone_host:
        kwargs["host"] = settings.pinecone_host
    pc = Pinecone(**kwargs)
    index = pc.Index(settings.pinecone_index)

    seen: dict[str, dict[str, Any]] = {}
    pagination_token: str | None = None
    while True:
        try:
            resp = index.list_paginated(limit=PAGE_SIZE, pagination_token=pagination_token)
        except Exception as exc:
            print(f"index.list_paginated failed ({exc}). Falling back to dummy-query scan.",
                  flush=True)
            return _fallback_scan(index)

        vectors = getattr(resp, "vectors", []) or []
        ids = [v.id for v in vectors] if vectors else []
        if not ids:
            break

        fetched = index.fetch(ids=ids)
        for vid, vec in (fetched.vectors or {}).items():
            meta = vec.metadata or {}
            num = str(meta.get("section_number", "")).strip()
            act = meta.get("act", "")
            key = f"{act}_{num}"
            if not num or key in seen:
                continue
            seen[key] = {
                "section_number": num,
                "section_title":  meta.get("section_title", ""),
                "act":            act,
                "category":       meta.get("category", ""),
                "text":           meta.get("pageContent") or meta.get("text", ""),
            }

        nxt = getattr(getattr(resp, "pagination", None), "next", None)
        if not nxt:
            break
        pagination_token = nxt

    return list(seen.values())


def _fallback_scan(index) -> list[dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    for n in range(1, 601):
        try:
            res = index.query(
                vector=[1e-6] * settings.embeddings_dim,  # Pinecone needs non-zero under cosine
                top_k=2,
                filter={"section_number": str(n)},
                include_metadata=True,
            )
            for m in (res.matches or []):
                meta = m.metadata or {}
                num = str(meta.get("section_number", "")).strip()
                act = meta.get("act", "")
                key = f"{act}_{num}"
                if num and key not in seen:
                    seen[key] = {
                        "section_number": num,
                        "section_title":  meta.get("section_title", ""),
                        "act":            act,
                        "category":       meta.get("category", ""),
                        "text":           meta.get("pageContent") or meta.get("text", ""),
                    }
        except Exception:
            continue
    return list(seen.values())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--enriched", default=str(DEFAULT_ENRICHED),
                        help="Path to sections_enriched.json (preferred source). "
                             "Set to '' to force Pinecone scan.")
    args = parser.parse_args()

    sections: list[dict[str, Any]] = []
    enriched_path = Path(args.enriched) if args.enriched else None
    if enriched_path and enriched_path.exists():
        print(f"→ loading sections from {enriched_path}…", flush=True)
        sections = load_from_enriched(enriched_path)
        print(f"   got {len(sections)} enriched sections (structured cross-refs)", flush=True)
    else:
        print(f"→ pulling sections from Pinecone index '{settings.pinecone_index}'…",
              flush=True)
        sections = iter_all_sections()
        print(f"   got {len(sections)} unique sections (Pinecone scan)", flush=True)

    if not sections:
        print("   nothing to build — exiting", flush=True)
        return

    graph = build_adjacency(sections)
    save_graph(graph, GRAPH_PATH)
    edges = sum(len(v) for v in graph["edges"].values()) // 2
    print(f"✓ wrote {GRAPH_PATH}: {len(graph['sections'])} nodes, {edges} edges",
          flush=True)


if __name__ == "__main__":
    main()
