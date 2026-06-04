"""seed_pinecone_v3 — same shape as v2 but adds K2 (separate summary vector per section).

v3 emits SEVEN vectors per section:
  - 1 anchor:    "ACT §N — title_clean\\n<short summary>\\n<body up to 1200 chars>"
  - 5 HQ:        one per hypothetical_question (high-recall for exact-question queries)
  - 1 summary:   summary text alone (high-recall for "explain what this does" queries)

The summary vector is K2 from the "best RAG" plan — it's a free recall lift on
"what does X do" queries where the user wants the gist, not the verbatim body.

Idempotent: same IDs as v2 plus -summary, so re-seeding upserts (overwrites old
vectors). Use --reset only if you want to wipe and start clean.

Usage:
  docker exec -w /app nyaya-backend python -m scripts.seed_pinecone_v3 --reset
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

CATEGORY_BY_ACT = {
    "BNS":  "Criminal_Laws",
    "BNSS": "Procedural_Law",
    "BSA":  "Evidence_Law",
}

MAX_ANCHOR_BODY_CHARS = 1200


def _index():
    from pinecone import Pinecone
    from urllib.parse import urlparse
    kwargs = {"api_key": settings.pinecone_api_key}
    if settings.pinecone_host:
        kwargs["host"] = settings.pinecone_host
    pc = Pinecone(**kwargs)

    if settings.pinecone_host:
        base = urlparse(settings.pinecone_host)  # noqa: F841
        info = pc.describe_index(settings.pinecone_index)
        idx_parsed = urlparse(info.host)
        index_host = f"http://host.docker.internal:{idx_parsed.port}"
        return pc.Index(settings.pinecone_index, host=index_host)

    return pc.Index(settings.pinecone_index)


def build_anchor_text(rec: dict) -> str:
    act = rec["act"]; num = rec["number"]
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
    """Section → up to 7 vectors (1 anchor + 5 HQ + 1 summary)."""
    act = rec["act"]; num = str(rec["number"])
    title = rec.get("title_clean") or rec.get("raw_title", "")
    category = CATEGORY_BY_ACT.get(act, "")
    body = rec.get("raw_body", "") or ""
    summary = (rec.get("summary") or "").strip()

    base_meta = {
        "act": act,
        "section_number": num,
        "section_title": title,
        "category": category,
        "pageContent": body[:2500],
    }
    out: list[dict] = []
    # Anchor
    out.append({
        "id":       f"{act}-{num}-anchor",
        "text":     build_anchor_text(rec),
        "metadata": {**base_meta, "vector_kind": "anchor"},
    })
    # HQ vectors
    for i, hq in enumerate((rec.get("hypothetical_questions") or [])[:5]):
        if not hq:
            continue
        out.append({
            "id":       f"{act}-{num}-hq{i}",
            "text":     hq,
            "metadata": {**base_meta, "vector_kind": "hq"},
        })
    # Summary vector (K2)
    if summary and len(summary) >= 20:
        out.append({
            "id":       f"{act}-{num}-summary",
            "text":     f"{act} §{num} — {title}: {summary}",
            "metadata": {**base_meta, "vector_kind": "summary"},
        })
    return out


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--in",          dest="in_path", default="/app/data/sections_enriched.json")
    p.add_argument("--batch",       type=int, default=500)
    p.add_argument("--concurrency", type=int, default=1)
    p.add_argument("--reset",       action="store_true")
    p.add_argument("--acts",        default="BNS,BNSS,BSA")
    p.add_argument("--limit",       type=int, default=0)
    p.add_argument("--dry-run",     action="store_true")
    args = p.parse_args()

    in_path = Path(args.in_path)
    if not in_path.exists():
        sys.exit(f"missing {in_path}")

    raw = json.loads(in_path.read_text())
    chosen = {a.strip().upper() for a in args.acts.split(",")}
    sections = [r for r in raw if r["act"] in chosen]
    if args.limit:
        sections = sections[: args.limit]
    print(f"loaded {len(sections)} sections from {in_path}")

    records: list[dict] = []
    for s in sections:
        records.extend(make_records_for_section(s))
    n_anchor = sum(1 for r in records if r["metadata"]["vector_kind"] == "anchor")
    n_hq     = sum(1 for r in records if r["metadata"]["vector_kind"] == "hq")
    n_sum    = sum(1 for r in records if r["metadata"]["vector_kind"] == "summary")
    print(f"  → {len(records)} vectors total ({n_anchor} anchor + {n_hq} HQ + {n_sum} summary)")

    if args.dry_run:
        for r in records[:3]:
            print(f"\nID: {r['id']}  text[:150]: {r['text'][:150]}")
        return

    index = _index()
    if args.reset:
        print("⚠  resetting Pinecone index...")
        try:
            index.delete(delete_all=True)
        except Exception as exc:
            print(f"   reset failed: {exc}")

    sem = asyncio.Semaphore(args.concurrency)
    t0 = time.perf_counter()
    batches = [records[i:i + args.batch] for i in range(0, len(records), args.batch)]
    print(f"\nembedding {len(records)} vectors in {len(batches)} batches "
          f"(batch={args.batch}, concurrency={args.concurrency})")
    upserted = 0

    async def process_batch(idx: int, batch: list[dict]) -> None:
        nonlocal upserted
        async with sem:
            texts = [r["text"] for r in batch]
            vectors = await embed_texts(texts)
            payload = [{"id": r["id"], "values": v, "metadata": r["metadata"]}
                       for r, v in zip(batch, vectors)]
            index.upsert(vectors=payload)
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
