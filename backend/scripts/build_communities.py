"""Detect entity communities in the KG (Leiden-style) + summarize each.

After build_lightrag_v2.py loads entities + edges, this script:

  1. Loads the KG into NetworkX.
  2. Runs the greedy modularity community detection algorithm (NetworkX's
     built-in; close to Leiden quality for our scale).
  3. Writes a `community_id` to each entity row in SQLite.
  4. For each community larger than 2 entities, asks the LLM for a one-sentence
     theme summary based on the member entity names + types.
  5. Writes the summaries to the `communities` table.

These communities power the HIGH-LEVEL retrieval path in legal_lightrag.py —
vague queries match a community summary first, then drill to its member
entities and their sections.

Cost: ~$0.05 (one LLM call per community summary, typically 30-80 communities).
Wall time: ~30s + 1-2 min for summaries (depending on community count).

Usage:
  docker exec -w /app nyaya-backend python -m scripts.build_communities
  docker exec -w /app nyaya-backend python -m scripts.build_communities --concurrency 50
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.llm import get_llm  # noqa: E402
from app.services.legal_lightrag import (   # noqa: E402
    Community,
    LegalKnowledgeGraph,
    _default_storage_dir,
)

_SUMMARY_SYS = """Summarize a community of Indian-legal entities AND generate
alternative search phrasings (keywords) for the community theme.

Return ONLY JSON:
{
  "summary":  "ONE short sentence (≤25 words) capturing the shared legal theme",
  "keywords": [<15-25 alternative phrasings users might type when looking for
               this theme — synonyms, layperson terms, related concepts>]
}

The summary should be CONCRETE, not generic. Bad: "various criminal offences".
Good: "Offences relating to theft, robbery, and dishonest taking of movable
property under BNS".

The keywords are for matching: include the obvious terms ("theft", "robbery")
AND layperson phrasings ("stealing", "took my phone", "shoplifting")  AND
adjacent legal concepts ("dishonest taking", "movable property", "wrongful
gain"). 15-25 entries. Lowercased. Short (1-4 words each).
"""


def _detect_communities(graph: LegalKnowledgeGraph) -> list[set[str]]:
    """NetworkX greedy modularity → returns list of node-id sets."""
    try:
        import networkx as nx
        from networkx.algorithms.community import greedy_modularity_communities
    except ImportError:
        sys.exit("networkx not installed")
    graph._build_graph()
    if graph._graph is None or graph._graph.number_of_nodes() == 0:
        return []
    # greedy_modularity works on undirected graphs
    g = graph._graph.to_undirected()
    # If MultiGraph, convert to weighted simple graph
    if g.is_multigraph():
        simple = nx.Graph()
        for u, v, data in g.edges(data=True):
            w = (data.get("confidence") or 0.5)
            if simple.has_edge(u, v):
                simple[u][v]["weight"] += w
            else:
                simple.add_edge(u, v, weight=w)
        # Add isolates too
        for n in g.nodes():
            if n not in simple:
                simple.add_node(n)
        g = simple
    communities = list(greedy_modularity_communities(g, weight="weight"))
    return [set(c) for c in communities]


async def _summarize_community(llm, members: list[dict], comm_id: int) -> Community:
    """One LLM call: name a community's theme AND generate K1 keyword expansion."""
    listing = "\n".join(
        f"  - {m['name']} ({m['type']}) — {m.get('description', '')[:60]}"
        for m in members[:30]
    )
    user_msg = (
        f"Community ID: {comm_id}\n"
        f"Members ({len(members)} entities):\n{listing}\n\n"
        "Produce a one-sentence summary AND 15-25 keyword phrasings users might "
        "type when searching for this theme."
    )
    try:
        data = await llm.complete_json(
            [
                {"role": "system", "content": _SUMMARY_SYS},
                {"role": "user",   "content": user_msg},
            ],
            fast=True,
            temperature=0.0,
            max_tokens=600,
        )
        summary = str(data.get("summary", "")).strip()
        kws_raw = data.get("keywords") or []
        keywords: list[str] = []
        seen: set[str] = set()
        for k in kws_raw:
            if not isinstance(k, str):
                continue
            k = k.strip().lower()
            if k and k not in seen and 2 <= len(k) <= 60:
                seen.add(k)
                keywords.append(k)
        keywords = keywords[:30]
    except Exception:
        summary = ""
        keywords = []
    return Community(id=comm_id, summary=summary, keywords=keywords,
                      entity_count=len(members))


async def run(args: argparse.Namespace) -> None:
    storage = Path(args.storage) if args.storage else _default_storage_dir()
    graph = LegalKnowledgeGraph(storage)
    stats = graph.stats()
    print(f"KG stats before: {stats}")

    if stats["entities"] == 0:
        sys.exit("no entities — run scripts.build_lightrag_v2 first")

    print("\n--- detecting communities (greedy modularity) ---")
    t0 = time.perf_counter()
    communities = _detect_communities(graph)
    print(f"  found {len(communities)} communities in {time.perf_counter() - t0:.1f}s")
    if not communities:
        return

    # Skip tiny communities (singletons / pairs are noise)
    big = [c for c in communities if len(c) >= args.min_size]
    print(f"  keeping {len(big)} with >= {args.min_size} members")

    # Persist community_id per entity
    print("\n--- writing community_id to entities ---")
    n_assigned = 0
    for cid, members_ids in enumerate(big):
        for eid in members_ids:
            graph.set_entity_community(eid, cid)
            n_assigned += 1
    print(f"  {n_assigned} entities classified")

    # Load member entity details for summarisation
    members_by_comm: dict[int, list[dict]] = {}
    c = graph.conn.cursor()
    for cid, members_ids in enumerate(big):
        rows = []
        placeholders = ",".join("?" * len(members_ids))
        c.execute(
            f"SELECT id, name, type, description, salience FROM entities "
            f"WHERE id IN ({placeholders}) ORDER BY salience DESC",
            list(members_ids),
        )
        for eid, name, etype, desc, sal in c.fetchall():
            rows.append({"id": eid, "name": name, "type": etype, "description": desc,
                          "salience": sal})
        members_by_comm[cid] = rows

    # Summarise in parallel
    print(f"\n--- LLM summaries for {len(big)} communities (concurrency={args.concurrency}) ---")
    llm = get_llm()
    sem = asyncio.Semaphore(args.concurrency)
    done = 0

    async def worker(cid: int, members: list[dict]) -> Community:
        nonlocal done
        async with sem:
            try:
                comm = await _summarize_community(llm, members, cid)
            except Exception as exc:
                print(f"    comm {cid}: {exc}")
                comm = Community(id=cid, summary="", entity_count=len(members))
            done += 1
            if done % 10 == 0 or done == len(big):
                print(f"    {done}/{len(big)} summarised", flush=True)
            return comm

    summaries = await asyncio.gather(
        *(worker(cid, members_by_comm[cid]) for cid in range(len(big)))
    )

    for comm in summaries:
        graph.upsert_community(comm)

    print("\n--- sample summaries + K1 keywords (top 5 largest communities) ---")
    biggest = sorted(summaries, key=lambda c: -c.entity_count)[:5]
    for c in biggest:
        print(f"  [community {c.id}, {c.entity_count} entities] {c.summary}")
        if c.keywords:
            print(f"    keywords ({len(c.keywords)}): {', '.join(c.keywords[:10])}{'...' if len(c.keywords) > 10 else ''}")

    print("\n--- final stats ---")
    print(graph.stats())


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--storage",     default=None)
    p.add_argument("--concurrency", type=int, default=50)
    p.add_argument("--min-size",    type=int, default=3,
                   help="ignore communities smaller than this (default 3)")
    args = p.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
