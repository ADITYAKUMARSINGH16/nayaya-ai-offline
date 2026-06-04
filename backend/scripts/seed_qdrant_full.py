"""Seed the Qdrant `rag-legal` collection from the enriched JSON file.
Usage:
    docker exec -w /app nyaya-backend python -m scripts.seed_qdrant_full
"""
import argparse
import asyncio
import json
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.services.embeddings import embed_texts
from scripts.seed_pinecone_v3 import make_records_for_section

async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--in", dest="in_path", default="/app/data/sections_enriched.json")
    p.add_argument("--batch", type=int, default=100)
    args = p.parse_args()

    in_path = Path(args.in_path)
    if not in_path.exists():
        sys.exit(f"missing {in_path}")

    raw = json.loads(in_path.read_text())
    print(f"loaded {len(raw)} sections from {in_path}")

    records = []
    for s in raw:
        records.extend(make_records_for_section(s))

    print(f"→ {len(records)} vectors total to seed into Qdrant collection '{settings.qdrant_collection}'")

    print("→ generating embeddings…", flush=True)
    # Process in batches to avoid OOM or timeout
    vectors = []
    text_batches = [records[i:i + args.batch] for i in range(0, len(records), args.batch)]
    for idx, batch in enumerate(text_batches):
        texts = [r["text"] for r in batch]
        v = await embed_texts(texts)
        vectors.extend(v)
        print(f"  embedded {len(vectors)}/{len(records)}")

    from qdrant_client import QdrantClient
    from qdrant_client.http import models

    client = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key or None)

    print("→ recreating collection…", flush=True)
    client.recreate_collection(
        collection_name=settings.qdrant_collection,
        vectors_config=models.VectorParams(size=settings.embeddings_dim, distance=models.Distance.COSINE),
    )

    qdrant_points = []
    for r, emb in zip(records, vectors):
        point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, r["id"]))
        qdrant_points.append(models.PointStruct(
            id=point_id,
            vector=emb,
            payload=r["metadata"]
        ))

    print(f"→ upserting in batches of {args.batch}…", flush=True)
    for i in range(0, len(qdrant_points), args.batch):
        batch = qdrant_points[i:i + args.batch]
        client.upsert(
            collection_name=settings.qdrant_collection,
            points=batch
        )
        print(f"   {min(i + args.batch, len(qdrant_points))}/{len(qdrant_points)} done", flush=True)

    stats = client.get_collection(collection_name=settings.qdrant_collection)
    print(f"✓ collection '{settings.qdrant_collection}' now holds {stats.points_count} vectors", flush=True)

if __name__ == "__main__":
    asyncio.run(main())
