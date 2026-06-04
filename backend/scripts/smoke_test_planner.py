"""Smoke-test the LLM query planner end-to-end.

Run inside the backend container:

  docker exec -w /app nyaya-backend python -m scripts.smoke_test_planner

Expected wall time: ~30-60 sec for 3 queries (5-10 LLM calls each).
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.query_planner import execute_plan_safe  # noqa: E402


QUERIES = [
    "BNS 202",
    "what is the punishment for theft",
    "my friend was arrested for theft, what next",
]


async def main():
    for q in QUERIES:
        print(f"\n=== Q: {q} ===")
        r = await execute_plan_safe(q)
        print(f"  intent:    {r.plan.intent}")
        print(f"  rewritten: {r.plan.rewritten_query}")
        print(f"  sub-queries:")
        for sq in r.plan.sub_queries:
            n_cites = len((sq.result or {}).get('citations', []))
            print(f"    [{sq.intent:11s}] q={sq.query[:55]!r:60s} quality={sq.quality:.2f} cites={n_cites}")
        cite_pairs = [f"{c['act']}§{c['section_number']}" for c in r.citations[:5]]
        print(f"  citations: {cite_pairs}")
        print(f"  confidence={r.confidence}  low_conf={r.low_confidence}")
        print(f"  answer[:300]: {r.answer}")
        if r.provenance:
            print(f"  provenance keys: {list(r.provenance.keys())}")


if __name__ == "__main__":
    asyncio.run(main())
