"""Run the labeled test set through the assistant API and log metrics.

Triggered by the n8n daily-eval cron. Can also be invoked manually:

    docker compose exec backend python -m eval.runner

Metrics logged to Supabase table `eval_runs`:
- precision_at_k    (citation overlap with expected_sections)
- citation_verified_rate (fraction of returned citations marked verified=true)
- latency_ms_p50 / p95
- raw per-case details (jsonb)
"""
from __future__ import annotations

import asyncio
import json
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any

# Allow `python eval/runner.py` invocation.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from app.services.db import _client  # noqa: E402

BACKEND_URL = os.getenv("EVAL_BACKEND_URL", "http://localhost:8000")
TEST_CASES = Path(__file__).parent / "test_cases.json"


async def _run_one(client: httpx.AsyncClient, case: dict[str, Any]) -> dict[str, Any]:
    t0 = time.perf_counter()
    try:
        r = await client.post(
            f"{BACKEND_URL}/api/assistant",
            json={
                "chatInput": case["query"],
                "sessionId": f"eval-{int(t0)}",
                "userId": None,
            },
            timeout=120.0,
        )
        ms = (time.perf_counter() - t0) * 1000
        r.raise_for_status()
        data = r.json()
    except Exception as exc:
        return {
            "query": case["query"],
            "expected": case["expected_sections"],
            "returned": [],
            "hit": False,
            "verified_rate": 0.0,
            "latency_ms": (time.perf_counter() - t0) * 1000,
            "error": str(exc),
        }

    returned = [str(c.get("section_number") or "") for c in (data.get("citations") or [])]
    expected = [str(s) for s in case["expected_sections"]]
    hit = any(s in returned for s in expected)

    verifs = [c.get("verified") for c in (data.get("citations") or []) if c.get("verified") is not None]
    verified_rate = (sum(1 for v in verifs if v) / len(verifs)) if verifs else 0.0

    return {
        "query": case["query"],
        "expected": expected,
        "returned": returned,
        "hit": hit,
        "verified_rate": verified_rate,
        "latency_ms": ms,
    }


async def main() -> None:
    cases = json.loads(TEST_CASES.read_text())["cases"]
    print(f"→ running {len(cases)} eval cases against {BACKEND_URL}", flush=True)

    async with httpx.AsyncClient() as client:
        results = []
        for c in cases:
            r = await _run_one(client, c)
            results.append(r)
            print(f"  {'✓' if r['hit'] else '✗'} {c['query'][:60]:60s}  {r['latency_ms']:6.0f}ms", flush=True)

    hits = sum(1 for r in results if r["hit"])
    latencies = [r["latency_ms"] for r in results]
    verified_rates = [r["verified_rate"] for r in results if r["verified_rate"] is not None]

    summary = {
        "total":                  len(results),
        "hits":                   hits,
        "precision_at_k":         hits / len(results) if results else 0.0,
        "citation_verified_rate": sum(verified_rates) / len(verified_rates) if verified_rates else 0.0,
        "latency_ms_p50":         statistics.median(latencies) if latencies else 0.0,
        "latency_ms_p95":         _percentile(latencies, 95)  if latencies else 0.0,
        "details":                results,
    }

    print(
        f"\n=== precision@k {summary['precision_at_k']:.2%} "
        f"verified {summary['citation_verified_rate']:.2%} "
        f"p50 {summary['latency_ms_p50']:.0f}ms p95 {summary['latency_ms_p95']:.0f}ms",
        flush=True,
    )

    try:
        _client().table("eval_runs").insert(summary).execute()
        print("✓ logged to Supabase eval_runs", flush=True)
    except Exception as exc:
        print(f"! could not log to Supabase: {exc}", flush=True)


def _percentile(values: list[float], p: int) -> float:
    if not values:
        return 0.0
    vs = sorted(values)
    k = (len(vs) - 1) * (p / 100)
    f, c = int(k), min(int(k) + 1, len(vs) - 1)
    return vs[f] + (vs[c] - vs[f]) * (k - f)


if __name__ == "__main__":
    asyncio.run(main())
