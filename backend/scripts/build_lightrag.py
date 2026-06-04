"""Build the LightRAG knowledge graph from data/sections_enriched.json.

For each of the ~1043 enriched sections, calls the LLM extractor twice:
  - pass 1: entities    (~$0.0005/section)
  - pass 2: relationships among those entities (~$0.0005/section)

Total ingest cost ≈ $1, wall time ≈ 10-15 min serial (faster with --concurrency).
Output: backend/data/lightrag/knowledge_graph.db (SQLite, ~5 MB).
Commit the DB to git so Render / Vercel / HF can use it without re-extracting.

Usage (inside the backend container):
    python -m scripts.build_lightrag
    python -m scripts.build_lightrag --limit 10            # smoke run
    python -m scripts.build_lightrag --concurrency 4       # faster
    python -m scripts.build_lightrag --acts BNS            # one act only
    python -m scripts.build_lightrag --resume              # skip sections already extracted
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.legal_lightrag import (   # noqa: E402
    LegalKnowledgeExtractor,
    LegalKnowledgeGraph,
    _default_storage_dir,
)


def _default_enriched_path() -> Path:
    if Path("/app/data").exists():
        return Path("/app/data/sections_enriched.json")
    return Path(__file__).resolve().parents[1] / "data" / "sections_enriched.json"


def _already_extracted(graph: LegalKnowledgeGraph, act: str, section_number: str) -> bool:
    """True if at least one entity in the DB has (act, section_number) already."""
    c = graph.conn.cursor()
    c.execute(
        "SELECT 1 FROM entities WHERE acts LIKE ? AND section_numbers LIKE ? LIMIT 1",
        (f'%"{act}"%', f'%"{section_number}"%'),
    )
    return c.fetchone() is not None


async def _process_section(
    sem: asyncio.Semaphore,
    extractor: LegalKnowledgeExtractor,
    graph: LegalKnowledgeGraph,
    rec: dict,
    idx: int,
    total: int,
) -> tuple[int, int]:
    """Extract entities+rels for one section and persist them. Returns (n_ents, n_rels)."""
    async with sem:
        act = rec.get("act", "")
        num = str(rec.get("number", ""))
        title = rec.get("title_clean") or rec.get("raw_title", "")
        body = rec.get("raw_body", "")
        try:
            ents, rels = await extractor.extract(
                act=act, section_number=num, section_title=title, section_body=body,
            )
        except Exception as exc:
            print(f"  [{idx}/{total}] {act} {num}: extraction failed — {exc}")
            return (0, 0)

        for e in ents:
            graph.add_entity(e)
        for r in rels:
            graph.add_relationship(r)
        print(f"  [{idx}/{total}] {act} {num}: {len(ents)} ents, {len(rels)} rels  ({title[:50]})")
        return (len(ents), len(rels))


async def run(args: argparse.Namespace) -> None:
    enriched_path = Path(args.enriched) if args.enriched else _default_enriched_path()
    if not enriched_path.exists():
        print(f"ERROR: enriched JSON not found at {enriched_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Reading {enriched_path}")
    records = json.loads(enriched_path.read_text())
    print(f"  → {len(records)} sections total")

    if args.acts:
        wanted = {a.strip().upper() for a in args.acts.split(",")}
        records = [r for r in records if (r.get("act") or "").upper() in wanted]
        print(f"  → {len(records)} after act filter ({sorted(wanted)})")
    if args.limit:
        records = records[: args.limit]
        print(f"  → {len(records)} after --limit {args.limit}")

    storage_dir = Path(args.storage) if args.storage else _default_storage_dir()
    storage_dir.mkdir(parents=True, exist_ok=True)
    print(f"Storage dir: {storage_dir}")

    graph = LegalKnowledgeGraph(storage_dir)
    extractor = LegalKnowledgeExtractor()

    # --resume: skip sections whose (act, number) already has at least one entity
    if args.resume:
        before = len(records)
        records = [r for r in records
                   if not _already_extracted(graph, r.get("act", ""), str(r.get("number", "")))]
        print(f"  → {len(records)} after --resume (skipped {before - len(records)} already-extracted)")

    if not records:
        print("Nothing to do.")
        return

    sem = asyncio.Semaphore(max(1, args.concurrency))
    t0 = time.time()
    tasks = [
        _process_section(sem, extractor, graph, rec, i + 1, len(records))
        for i, rec in enumerate(records)
    ]
    results = await asyncio.gather(*tasks)
    elapsed = time.time() - t0

    total_ents = sum(r[0] for r in results)
    total_rels = sum(r[1] for r in results)
    final_stats = graph.stats()
    print(
        f"\nDone in {elapsed:.1f}s — extracted {total_ents} entities, {total_rels} relationships."
        f"\nDB now contains {final_stats['entities']} unique entities and "
        f"{final_stats['relationships']} unique relationships."
    )
    print(f"DB path: {storage_dir / 'knowledge_graph.db'}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the LightRAG knowledge graph.")
    parser.add_argument("--enriched", help="Path to sections_enriched.json")
    parser.add_argument("--storage",  help="Output directory for knowledge_graph.db")
    parser.add_argument("--limit",    type=int, default=0, help="Process only first N sections (smoke run)")
    parser.add_argument("--concurrency", type=int, default=3, help="Parallel LLM calls (default 3)")
    parser.add_argument("--acts", help="Comma-separated act filter, e.g. 'BNS' or 'BNS,BNSS'")
    parser.add_argument("--resume", action="store_true",
                        help="Skip sections already present in the DB")
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
