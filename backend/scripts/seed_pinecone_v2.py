"""Re-seed Pinecone from data/sections_enriched.json.

Replaces the OLD vectors (built from contaminated bodies with marginalia bleed
in BNSS §35 etc., missing BSA §109-116, etc.) with CLEAN vectors built from
the v2 chunker + enricher output.

Per section we emit SIX vectors for high-recall retrieval:
  - 1 anchor:    "ACT §N — title_clean\\n<short summary>\\n<body up to 1200 chars>"
  - 5 HQ:        one vector per hypothetical_question, so a question like
                 "punishment for theft" embedded directly hits BNS §303's HQ vector.

All vectors share the same metadata (act, section_number, section_title,
category, pageContent). At query time we collapse by section_number to keep
results focused.

Costs (text-embedding-3-small @ 768-dim):
  6354 vectors × ~200 input tokens = ~1.3M tokens × $0.02/M = ~$0.03
Wall: ~3-5 min at concurrency 50 (OpenAI Tier 3 friendly).

Usage:
  docker exec -w /app nyaya-backend python -m scripts.seed_pinecone_v2 --reset
  docker exec -w /app nyaya-backend python -m scripts.seed_pinecone_v2 --concurrency 50
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402
from app.services.embeddings import embed_texts  # noqa: E402

# Categories used by routing — derived from act
CATEGORY_BY_ACT = {
    "BNS": "Criminal_Laws",
    "BNSS": "Procedural_Law",
    "BSA": "Evidence_Law",
}

MAX_ANCHOR_BODY_CHARS = 1200


def _index():
    from pinecone import Pinecone
    pc = Pinecone(api_key=settings.pinecone_api_key)
    return pc.Index(settings.pinecone_index)


def build_anchor_text(rec: dict) -> str:
    act = rec["act"]
    num = rec["number"]
    title = rec.get("title_clean") or rec.get("raw_title", "")
    summary = (rec.get("summary") or "").strip()
    body = (rec.get("raw_body") or "")[:MAX_ANCHOR_BODY_CHARS]
    parts = [f"{act} §{num} — {title}".strip()]
    if summary:
        parts.append(summary)
    if body:
        parts.append(body)
    return "\n".join(parts)


def make_records_for_section(rec: dict) -> list[dict]:
    """One section → up to 6 vector candidates (1 anchor + 5 HQ).

    Each candidate is a dict ready for Pinecone upsert (text → will be embedded).
    """
    act = rec["act"]
    num = str(rec["number"])
    title = rec.get("title_clean") or rec.get("raw_title", "")
    category = CATEGORY_BY_ACT.get(act, "")
    body = rec.get("raw_body", "") or ""

    out = []
    # Anchor
    out.append({
        "id": f"{act}-{num}-anchor",
        "text": build_anchor_text(rec),
        "metadata": {
            "act": act,
            "section_number": num,
            "section_title": title,
            "category": category,
            "pageContent": body[:2500],
            "vector_kind": "anchor",
        },
    })
    # HQ vectors
    for i, hq in enumerate((rec.get("hypothetical_questions") or [])[:5]):
        if not hq:
            continue
        out.append({
            "id": f"{act}-{num}-hq{i}",
            "text": hq,
            "metadata": {
                "act": act,
                "section_number": num,
                "section_title": title,
                "category": category,
                "pageContent": body[:2500],
                "vector_kind": "hq",
            },
        })
    return out


async def embed_batch(texts: list[str], concurrency_sem: asyncio.Semaphore) -> list[list[float]]:
    """Embed a batch of texts. embed_texts already chunks internally; we just bound concurrency."""
    async with concurrency_sem:
        return await embed_texts(texts)


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--in",          dest="in_path", default="/app/data/sections_enriched.json")
    parser.add_argument("--batch",       type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=10,
                        help="parallel embed-batch calls (each batch is up to --batch)")
    parser.add_argument("--reset",       action="store_true",
                        help="delete all vectors in the index before upserting")
    parser.add_argument("--acts",        default="BNS,BNSS,BSA")
    parser.add_argument("--limit",       type=int, default=0,
                        help="cap sections (smoke test)")
    parser.add_argument("--dry-run",     action="store_true")
    args = parser.parse_args()

    in_path = Path(args.in_path)
    if not in_path.exists():
        sys.exit(f"missing {in_path}")

    raw = json.loads(in_path.read_text())
    chosen = {a.strip().upper() for a in args.acts.split(",")}
    sections = [r for r in raw if r["act"] in chosen]
    if args.limit:
        sections = sections[: args.limit]
    print(f"loaded {len(sections)} sections from {in_path}")

    # Build all records (anchor + HQ per section)
    records: list[dict] = []
    for s in sections:
        records.extend(make_records_for_section(s))
    print(f"  → {len(records)} candidate vectors (anchor + HQ)")

    if args.dry_run:
        for r in records[:3]:
            print(f"\nID: {r['id']}")
            print(f"  text[:200]: {r['text'][:200]}")
            print(f"  metadata: {r['metadata']}")
        return

    index = _index()
    if args.reset:
        print("⚠  resetting Pinecone index (deleting all vectors)...")
        try:
            index.delete(delete_all=True)
            print("   reset done")
        except Exception as exc:
            print(f"   reset failed: {exc}")

    # Embed in batches with bounded concurrency
    sem = asyncio.Semaphore(args.concurrency)
    t0 = time.perf_counter()
    batches: list[list[dict]] = [records[i:i + args.batch] for i in range(0, len(records), args.batch)]
    print(f"\nembedding {len(records)} vectors in {len(batches)} batches "
          f"(batch={args.batch}, concurrency={args.concurrency})")

    upserted = 0

    async def process_batch(idx: int, batch: list[dict]) -> None:
        nonlocal upserted
        texts = [r["text"] for r in batch]
        vectors = await embed_batch(texts, sem)
        # Upsert (Pinecone client is sync; small batches so fine)
        upsert_payload = [
            {"id": r["id"], "values": v, "metadata": r["metadata"]}
            for r, v in zip(batch, vectors)
        ]
        index.upsert(vectors=upsert_payload)
        upserted += len(batch)
        elapsed = time.perf_counter() - t0
        rate = upserted / max(elapsed, 0.1)
        eta = (len(records) - upserted) / max(rate, 0.1)
        print(f"  batch {idx + 1}/{len(batches)}  {upserted}/{len(records)} "
              f"({rate:.1f}/s, eta {eta:.0f}s)", flush=True)

    await asyncio.gather(*(process_batch(i, b) for i, b in enumerate(batches)))

    print(f"\n✓ upserted {upserted} vectors in {time.perf_counter() - t0:.1f}s")
    print(f"  index stats: {index.describe_index_stats()}")


if __name__ == "__main__":
    asyncio.run(main())
