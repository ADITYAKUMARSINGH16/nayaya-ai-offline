"""Build LightRAG KG v2 from sections_enriched.json.

Three sources of graph content (in order of trust):

  1. ENTITIES from enricher (zero LLM cost here — already done in pass 1).
     Each entity comes with salience, type, description from enrich_sections_v2.

  2. CROSS-REFERENCES from enricher (zero LLM cost). The 685 validated
     cross-refs become REFERENCES edges with kind='structured' and
     confidence=1.0. This is the highest-quality edge type — every one points
     to a real section in our corpus and has a quoted source phrase.

  3. INTRA-SECTION RELATIONSHIPS via LLM (1 call per section, ~$0.10 total).
     The LLM is constrained to the entity list from the enricher — it can ONLY
     produce relationships between known entities. Output is post-validated.
     These edges get kind='llm' and confidence ≤0.9.

Storage: data/lightrag/knowledge_graph.db (replaces v1 schema).

Usage (inside container):
  docker exec -w /app nyaya-backend python -m scripts.build_lightrag_v2
  docker exec -w /app nyaya-backend python -m scripts.build_lightrag_v2 --reset --concurrency 100
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
    LegalEntity,
    LegalKnowledgeGraph,
    LegalRelationship,
    extract_relationships,
    _default_storage_dir,
)
from app.core.llm import get_llm   # noqa: E402

# ---------------------------------------------------------------------------
# Step 1: load entities from enriched JSON (no LLM)
# ---------------------------------------------------------------------------

def load_entities_from_enriched(graph: LegalKnowledgeGraph, records: list[dict]) -> dict[tuple[str, str], list[dict]]:
    """Insert all entities into the KG. Return a (act, section) → [entity{id, name, type, ...}]
    map so the relationship-extraction step knows what entity IDs to link to."""
    by_section: dict[tuple[str, str], list[dict]] = {}
    n_inserted = 0
    for rec in records:
        act = rec["act"]
        sec = str(rec["number"])
        ents = []
        for e in rec.get("entities", []):
            if not isinstance(e, dict):
                continue
            try:
                sal = float(e.get("salience", 0.5))
            except (ValueError, TypeError):
                sal = 0.5
            entity = LegalEntity(
                id="",
                name=str(e.get("name", "")).strip(),
                type=str(e.get("type", "")).strip().upper(),
                description=str(e.get("description", "")).strip(),
                section_numbers=[sec],
                acts=[act],
                salience=max(0.3, min(1.0, sal)),
            )
            if not entity.name:
                continue
            ent_id = graph.add_entity(entity)
            ents.append({
                "id": ent_id,
                "name": entity.name,
                "type": entity.type,
                "salience": entity.salience,
            })
            n_inserted += 1
        by_section[(act, sec)] = ents
    print(f"  entities inserted: {n_inserted}")
    return by_section


# ---------------------------------------------------------------------------
# Step 2: load cross-references as STRUCTURED edges (no LLM)
# ---------------------------------------------------------------------------

def load_cross_refs(graph: LegalKnowledgeGraph,
                    records: list[dict],
                    section_entities: dict[tuple[str, str], list[dict]]) -> None:
    """For each cross_ref in enriched JSON, create a REFERENCES edge between
    the SECTION-LEVEL representation of source and target.

    We don't have section-as-entity nodes yet. Strategy: pick the highest-
    salience entity in the source section as the canonical source, and the
    highest-salience entity in the target section as the canonical target.
    If the target section has no entities (rare), skip.
    """
    n_edges = 0
    for rec in records:
        src_act = rec["act"]
        src_sec = str(rec["number"])
        src_ents = section_entities.get((src_act, src_sec), [])
        if not src_ents:
            continue
        # Canonical source = highest-salience entity in this section
        src = max(src_ents, key=lambda e: e["salience"])
        for xref in rec.get("cross_references", []):
            tgt_act = str(xref.get("act", "")).upper()
            tgt_sec = str(xref.get("number", "")).strip()
            if not tgt_sec:
                continue
            tgt_ents = section_entities.get((tgt_act, tgt_sec), [])
            if not tgt_ents:
                continue
            tgt = max(tgt_ents, key=lambda e: e["salience"])
            if src["id"] == tgt["id"]:
                continue
            desc = str(xref.get("description", "")).strip() or f"{src_act} §{src_sec} references {tgt_act} §{tgt_sec}"
            rel = LegalRelationship(
                id="",
                source_id=src["id"],
                target_id=tgt["id"],
                relation_type="REFERENCES",
                description=desc[:200],
                section_numbers=[src_sec],
                kind="structured",
                confidence=1.0,
            )
            graph.add_relationship(rel)
            n_edges += 1
    print(f"  cross-ref edges inserted: {n_edges}")


# ---------------------------------------------------------------------------
# Step 3: intra-section relationships via LLM (concurrency-bounded)
# ---------------------------------------------------------------------------

async def extract_intra_section_relationships(
    graph: LegalKnowledgeGraph,
    records: list[dict],
    section_entities: dict[tuple[str, str], list[dict]],
    *,
    concurrency: int = 100,
) -> None:
    llm = get_llm()
    sem = asyncio.Semaphore(concurrency)
    completed = 0
    failed = 0
    n_edges = 0
    t0 = time.perf_counter()

    eligible = [r for r in records if len(section_entities.get((r["act"], str(r["number"])), [])) >= 2]
    print(f"  intra-section LLM passes: {len(eligible)} sections with >=2 entities")

    async def worker(rec: dict) -> None:
        nonlocal completed, failed, n_edges
        async with sem:
            try:
                rels = await extract_relationships(
                    llm,
                    section_body=rec.get("raw_body", "") or "",
                    entities=section_entities[(rec["act"], str(rec["number"]))],
                    section_number=str(rec["number"]),
                    act=rec["act"],
                )
                for r in rels:
                    graph.add_relationship(r)
                    n_edges += 1
            except Exception as exc:
                failed += 1
                print(f"    {rec['act']} §{rec['number']}: {exc}", flush=True)
            completed += 1
            if completed % 50 == 0 or completed == len(eligible):
                elapsed = time.perf_counter() - t0
                rate = completed / max(elapsed, 0.1)
                eta = (len(eligible) - completed) / max(rate, 0.1)
                print(f"    {completed}/{len(eligible)}  ({rate:.1f}/s, eta {eta:.0f}s, "
                      f"failed={failed}, edges={n_edges})", flush=True)

    await asyncio.gather(*(worker(r) for r in eligible))


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

async def run(args: argparse.Namespace) -> None:
    enriched = Path(args.enriched)
    if not enriched.exists():
        sys.exit(f"missing {enriched} — run scripts.chunk_pdfs + scripts.enrich_sections_v2 first")
    records = json.loads(enriched.read_text())
    if args.acts:
        wanted = {a.strip().upper() for a in args.acts.split(",")}
        records = [r for r in records if r["act"] in wanted]
    if args.limit:
        records = records[: args.limit]
    print(f"loaded {len(records)} enriched sections")

    storage = Path(args.storage) if args.storage else _default_storage_dir()
    graph = LegalKnowledgeGraph(storage)

    if args.reset:
        print("--- RESET KG ---")
        graph.reset()

    print("\n--- step 1: load entities from enriched JSON ---")
    section_entities = load_entities_from_enriched(graph, records)

    print("\n--- step 2: load cross-reference edges (structured, no LLM) ---")
    load_cross_refs(graph, records, section_entities)

    print(f"\n--- step 3: intra-section relationships via LLM (concurrency={args.concurrency}) ---")
    await extract_intra_section_relationships(graph, records, section_entities,
                                                concurrency=args.concurrency)

    print("\n--- final stats ---")
    print(graph.stats())


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--enriched",     default="/app/data/sections_enriched.json")
    p.add_argument("--storage",      default=None)
    p.add_argument("--concurrency",  type=int, default=100)
    p.add_argument("--limit",        type=int, default=0)
    p.add_argument("--acts",         default="")
    p.add_argument("--reset",        action="store_true",
                   help="wipe entities + relationships + communities before rebuild")
    args = p.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
