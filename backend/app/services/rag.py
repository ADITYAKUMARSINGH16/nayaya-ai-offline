"""Unified retrieval — v3 (HyDE + decomposition + relevance judge + KG-aware).

Pipeline:

  Query
    │
    ▼
  LLM Router (one call, memoized) → {acts, intent, section_hint, act_explicit,
                                       low_kw, high_kw, sub_queries}
    │
    ├─ Tier 1: CITATION LOOKUP                 (act_explicit + section_hint + literal-act-in-query)
    │     → direct hash hit
    │     → ENRICH (C): + KG community siblings as "related sections"
    │     → return immediately
    │
    └─ Tier 2: UNIFIED SEMANTIC ENGINE          (everything else)
          │
          ▼
        FAN-OUT over sub-queries (H4):
          for each sub_q in (sub_queries or [original_query]):
            ┌──────────────────────────────────────────────────────────────┐
            │ a) HyDE (H1): LLM writes a hypothetical statute paragraph    │
            │    for sub_q → embed THAT instead of the raw query           │
            │ b) Pinecone vector search (acts-filtered, over-fetch)        │
            │ c) BM25 over candidate pool                                   │
            │ d) KG LOW path  (low_kw → entity → salience-ranked sections) │
            │ e) KG HIGH path (LLM ranks communities → member sections)    │
            │ f) section_hint lookup (if router emitted one)               │
            └──────────────────────────────────────────────────────────────┘
          │
          ▼
        UNION + salience-weighted RRF (A: LOW + HIGH as SEPARATE streams)
          │
          ▼
        RELEVANCE JUDGE (H3): one LLM call drops candidates that don't
        actually answer the query. Adversarial filter.
          │
          ▼
        FINAL LLM RERANK (with G: salience-aware tiebreaker)
          │
          ▼
        BUILD CONTEXT (B): community summaries prepended as "Topic: ..."
        headers before the section bodies. Citations now include `related`
        sections from KG and `kg_facts` from relationships.

  Plus the new substring-cross-check in Tier 1 (prefer act actually typed).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.services import act_router, legal_lightrag, section_lookup
from app.services.rerank import bm25_search
from app.services.vector_store import search_sections

log = logging.getLogger(__name__)

MAX_SECTION_CHARS = 5000   # generous — full bodies fit including punishment clauses at end
RRF_K = 60
LOW_CONFIDENCE_THRESHOLD = 0.25
VECTOR_OVERFETCH = 4

USE_LLM_RERANK = True
USE_HYDE = True
USE_DECOMPOSITION = True
USE_RELEVANCE_JUDGE = True
USE_ELEMENT_MATCHER = True   # APPLY_FACTS only — IRAC element-vs-fact check

RERANK_MIN_SCORE = 4
RERANK_MIN_RESULTS = 3
RERANK_MAX_RESULTS = 8

# For APPLY_FACTS inputs (case-fact narratives — trial endpoint, FIR drafter)
# the relevance judge should be MORE INCLUSIVE because the judge LLM needs
# multiple candidate sections to do real element-matching. Aggressive dropping
# leaves only 1-2 candidates and the trial gets the wrong section.
APPLY_FACTS_MIN_KEEP = 6           # vs 3 default
APPLY_FACTS_MIN_SCORE = 3          # vs 4 default

# Per-stream RRF weights — higher = stronger boost per rank position
RRF_WEIGHTS = {
    "vector":         1.0,
    "bm25":           1.0,
    "kg_low":         1.5,   # entity-name match — strong signal
    "kg_high":        1.0,   # community theme match — softer signal
    "section_lookup": 2.0,   # explicit number reference — strongest
}


# ---- HyDE (H1) ------------------------------------------------------------

_HYDE_SYS = """You write a SHORT (3-5 sentences) hypothetical Indian-statute
paragraph that would answer the user's query, in the formal register of the
BNS / BNSS / BSA acts.

The output is used as an embedding source, not shown to the user. Don't
preamble. Don't say "this section" or refer to numbering. Just write the
substantive content as if it were a section body. If the query asks about a
section number ("BNS 202"), write what that section's body might plausibly say.

If the query is too vague for a substantive answer, return a 1-2 sentence
restatement of the query in statute-style language."""


async def _hyde_expand(query: str) -> str:
    """Generate a hypothetical-statute paragraph for the query (H1).

    Returns the raw query on any LLM error so vector search still works.
    """
    try:
        from app.core.llm import get_llm
        llm = get_llm()
        out = await llm.complete(
            [
                {"role": "system", "content": _HYDE_SYS},
                {"role": "user",   "content": query[:500]},
            ],
            fast=True,
            temperature=0.0,
            max_tokens=300,
        )
        out = (out or "").strip()
        return out if len(out) > 30 else query   # fall back if too short
    except Exception as exc:
        log.warning("HyDE failed; using raw query: %s", exc)
        return query


# ---- H3: per-result relevance judge ---------------------------------------

_RELEVANCE_JUDGE_SYS = """Score each candidate section 0-10 for whether it
DIRECTLY answers the user's query. Drop candidates that are tangential or
unrelated.

  10 = exact match — this section IS the answer
  7  = closely related, would appear in the answer
  4  = tangentially related
  1  = mentioned but not actually relevant
  0  = unrelated noise

Return ONLY JSON: {"keep": [<section_number string>, ...]}
Only include sections you'd score >= 5.
"""


async def _relevance_judge(query: str, candidates: list[dict[str, Any]],
                            *, max_keep: int = 12,
                            min_keep: int = 3,
                            min_score: int = 5) -> list[dict[str, Any]]:
    """Drop irrelevant candidates with an adversarial LLM check (H3).

    min_keep / min_score are tunable per intent — APPLY_FACTS uses more
    lenient thresholds because the downstream judge needs multiple options
    for element-matching.

    Falls back to keeping all candidates on any error.
    """
    if not candidates or len(candidates) <= min_keep:
        return candidates
    try:
        from app.core.llm import get_llm
        llm = get_llm()
        lines = []
        for r in candidates[:20]:
            snippet = (r.get("text") or "")[:200].replace("\n", " ")
            lines.append(
                f"[{r['section_number']}] {r['act']} §{r['section_number']} "
                f"{r['section_title']}: {snippet}"
            )
        # Inject the threshold into the user message so the LLM uses it
        user_msg = (f"QUERY: {query[:300]}\n\n"
                    f"Drop candidates you'd score below {min_score}/10. "
                    f"Keep AT LEAST {min_keep} candidates.\n\nCANDIDATES:\n"
                    + "\n".join(lines))
        data = await llm.complete_json(
            [
                {"role": "system", "content": _RELEVANCE_JUDGE_SYS},
                {"role": "user",   "content": user_msg},
            ],
            fast=True,
            temperature=0.0,
            max_tokens=500,
        )
        keep_set = {str(s) for s in (data.get("keep") or []) if s}
        if not keep_set:
            return candidates[: max_keep]
        kept = [r for r in candidates if str(r["section_number"]) in keep_set]
        # Always keep at least min_keep to avoid empty answers
        if len(kept) < min_keep:
            extras = [r for r in candidates if r not in kept][: min_keep - len(kept)]
            kept = kept + extras
        return kept[:max_keep]
    except Exception as exc:
        log.warning("relevance judge failed; keeping all candidates: %s", exc)
        return candidates[: max_keep]


# ---- Element matcher (NEW — APPLY_FACTS-only IRAC check) -----------------

_ELEMENT_MATCHER_SYS = """You apply IRAC element-matching to filter candidate
Indian legal sections against a case-fact narrative.

For EACH candidate section, ask: do the case facts actually establish ALL
the key elements/predicates of the offence or rule defined by this section?

  YES → keep the section
  NO  → drop the section (even if it's tangentially related to the topic)

COMMON ELEMENT TRAPS in Indian criminal law (BNS 2023):
  - §303 Theft: dishonest + movable property + moves it + without consent.
    Does NOT require force, threat, entrustment, or breaking in.
  - §304 Snatching: requires SUDDEN FORCE or swift seizure.
    Without force/suddenness, it's NOT snatching — it's theft.
  - §305 Theft in dwelling/transport: requires the act was IN a dwelling
    or means of transport. "From a bag at a metro platform" → NOT §305
    (the platform isn't a dwelling and the bag isn't transport).
  - §306 Theft by clerk/servant: requires the EMPLOYMENT relationship.
    Without it, NOT §306.
  - §307 Theft after preparation for hurt: requires PREPARATION TO CAUSE
    DEATH/HURT. Just taking quietly is NOT §307.
  - §309 Robbery: requires force OR threat of force.
    Without force/threat, NOT robbery.
  - §310 Dacoity: requires 5 OR MORE PERSONS committing robbery.
  - §316 Criminal breach of trust: requires the property was ENTRUSTED to
    the accused. A stranger taking from someone's bag is NOT §316.
  - §318 Cheating: requires DECEIT/MISREPRESENTATION inducing delivery.
    Without deceit, NOT cheating — could be theft.

For sections not in the above list: analyse the section's own statute text
(visible in the candidate) and apply the same logic.

DEFAULT TO INCLUSIVE: keep a section unless you can identify a SPECIFIC
element the facts don't satisfy. When in doubt, keep.

PARENT-PRESERVATION (CRITICAL):
A specialised variant always implies the parent offence. If you keep ANY
variant, you MUST also keep the parent base section. Parent → variant pairs:
  - §303 Theft (parent) ← §305 (in dwelling), §306 (by clerk), §307 (after
    preparation), §313 (by gang). If any of §305/306/307/313 survives, KEEP §303.
  - §309 Robbery (parent) ← §310 Dacoity (5+ persons). If §310 survives,
    KEEP §309.
  - §103 Murder (parent) ← §104 Murder by life-convict. If §104 survives,
    KEEP §103.
  - §115 Voluntarily causing hurt (parent) ← §117 Grievous hurt. If §117
    survives, KEEP §115.
The reason: a judge needs to see the GENUS offence even when a SPECIES applies,
because the species' aggravating element might not be proved at trial — the
genus may still hold.

Return ONLY JSON:
{
  "keep": [<section_number string>, ...],
  "drop_reasons": {"<section_number>": "<specific missing element>"}
}
"""

# Parent-section preservation map for the post-LLM safety net. Even if the
# LLM forgets the parent-preservation rule, we re-add the parent here.
# Format: { variant_section_number: parent_section_number }
_PARENT_OF_VARIANT: dict[str, str] = {
    # Theft chapter (BNS)
    "305": "303",   # Theft in dwelling → Theft
    "306": "303",   # Theft by clerk    → Theft
    "307": "303",   # Theft after prep  → Theft
    "313": "303",   # Theft by gang     → Theft
    # Robbery / Dacoity
    "310": "309",   # Dacoity           → Robbery
    # Murder
    "104": "103",   # Murder by life-convict → Murder
    # Hurt
    "117": "115",   # Grievous hurt     → Hurt
}


async def _element_matcher(
    case_facts: str,
    candidates: list[dict[str, Any]],
    *,
    min_keep: int = 3,
) -> list[dict[str, Any]]:
    """IRAC element-matching judge. Drops sections whose elements aren't
    satisfied by the case facts. APPLY_FACTS-only by design — generic
    queries don't have "facts" in the legal sense.

    Conservative: keeps a minimum of min_keep candidates even if all drop.
    Falls back to keeping all candidates on any error.
    """
    if not candidates or len(candidates) <= min_keep:
        return candidates
    try:
        from app.core.llm import get_llm
        llm = get_llm()
        lines = []
        for r in candidates[:15]:   # element matching is heavier, cap input
            # Element matcher needs FULL section text to judge — no clip
            snippet = (r.get("text") or "")[:1500].replace("\n", " ")
            lines.append(
                f"[{r['section_number']}] {r['act']} §{r['section_number']} "
                f"{r['section_title']}\n  TEXT: {snippet}"
            )
        user_msg = (f"CASE FACTS:\n{case_facts[:2000]}\n\n"
                    f"CANDIDATE SECTIONS:\n" + "\n\n".join(lines))
        data = await llm.complete_json(
            [
                {"role": "system", "content": _ELEMENT_MATCHER_SYS},
                {"role": "user",   "content": user_msg},
            ],
            fast=True,
            temperature=0.0,
            max_tokens=1200,
        )
        keep_set = {str(s) for s in (data.get("keep") or []) if s}
        if not keep_set:
            log.warning("element_matcher kept nothing — preserving original ordering")
            return candidates

        # Parent-preservation safety net: if any variant survives but its
        # parent doesn't, add the parent back from candidates.
        for sn in list(keep_set):
            parent = _PARENT_OF_VARIANT.get(sn)
            if parent and parent not in keep_set:
                # Check the parent is in the candidate pool
                if any(str(r["section_number"]) == parent for r in candidates):
                    keep_set.add(parent)
                    log.info("element_matcher: re-adding parent §%s for variant §%s", parent, sn)

        kept = [r for r in candidates if str(r["section_number"]) in keep_set]
        if len(kept) < min_keep:
            # Top up with rejected candidates to maintain breadth
            extras = [r for r in candidates if r not in kept][: min_keep - len(kept)]
            kept = kept + extras
        # Log drop reasons for debugging
        if data.get("drop_reasons"):
            log.info("element_matcher dropped: %s", data["drop_reasons"])
        return kept
    except Exception as exc:
        log.warning("element matcher failed; keeping all candidates: %s", exc)
        return candidates


# ---- helpers --------------------------------------------------------------

def _to_text_citation(rec: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Build a (context_block, citation_dict) pair.

    The context block surfaces SUMMARY + PUNISHMENT + body excerpt so the
    answer LLM always has the punishment text (which often lives at the end
    of long bodies and would otherwise be truncated away).
    """
    label = f"{rec.get('act','')} Section {rec.get('section_number','')}: {rec.get('section_title','')}".strip()
    text = (rec.get("text") or "")[:MAX_SECTION_CHARS]

    # Augment from sections_enriched.json (always available, in-memory)
    meta = section_lookup.get_metadata(
        rec.get("act", ""), rec.get("section_number", ""),
    ) or {}
    summary = (rec.get("summary") or meta.get("summary") or "").strip()
    punishment = rec.get("punishment") or meta.get("punishment")

    block_parts = [label]
    if summary and len(text) < 1800:
        block_parts.append(f"Summary: {summary}")
    if punishment:
        block_parts.append(f"Punishment: {punishment}")
    if text:
        block_parts.append(f"Text: {text}")
    block = "\n".join(block_parts)

    citation = {
        "act":             rec.get("act", ""),
        "section_number":  rec.get("section_number", ""),
        "section_title":   rec.get("section_title", ""),
        "score":           rec.get("score"),
        "snippet":         text[:400],
        "punishment":      punishment,
        "related":         rec.get("related", []),
    }
    return block, citation


def _build_payload(records: list[dict[str, Any]], *,
                   low_confidence: bool,
                   debug: dict[str, Any],
                   community_summaries: list[str] | None = None,
                   kg_facts: list[str] | None = None) -> dict[str, Any]:
    """Build the final RAG response.

    Context now leads with:
      - community summary headers (B)   — "Topic: ..."
      - kg_facts                        — bullet relationships
    followed by the section bodies. The LLM answer agent sees this whole block.
    """
    blocks: list[str] = []
    citations: list[dict[str, Any]] = []

    if community_summaries:
        blocks.append("### Relevant topics:\n" + "\n".join(f"- {s}" for s in community_summaries))
    if kg_facts:
        blocks.append("### Related facts from the knowledge graph:\n" +
                       "\n".join(f"- {f}" for f in kg_facts[:8]))

    for rec in records:
        b, c = _to_text_citation(rec)
        blocks.append(b)
        citations.append(c)

    return {
        "context":        "\n\n".join(blocks),
        "citations":      citations,
        "low_confidence": low_confidence if records else True,
        "debug":          debug,
    }


def _collapse_by_section(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Multi-vector ingest emits ~7 vectors per section. Keep the best per section_number."""
    best: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for r in records:
        n = str(r.get("section_number") or "")
        if not n:
            continue
        score = r.get("score") or 0.0
        cur = best.get(n)
        if cur is None or score > (cur.get("score") or 0.0):
            best[n] = r
            if n not in order:
                order.append(n)
    return [best[n] for n in order]


def _doc_for_bm25(record: dict[str, Any]) -> str:
    return " ".join([
        record.get("section_title", ""),
        record.get("act", ""),
        (record.get("text") or "")[:600],
    ])


def _weighted_rrf(ranked_lists: list[tuple[list[str], float]], *,
                   k: int = RRF_K, top_k: int = 30) -> list[str]:
    """RRF with per-source weight multipliers."""
    scores: dict[str, float] = {}
    for items, weight in ranked_lists:
        for rank, sn in enumerate(items):
            if not sn:
                continue
            scores[sn] = scores.get(sn, 0.0) + weight * (1.0 / (k + rank))
    ranked = sorted(scores.items(), key=lambda x: -x[1])
    return [sn for sn, _ in ranked[:top_k]]


def _kg_facts_from_relationships(relationships: list[dict[str, Any]]) -> list[str]:
    """Convert KG relationships into one-line readable facts for the LLM context."""
    out: list[str] = []
    for r in relationships[:8]:
        src = r.get("source", ""); tgt = r.get("target", ""); rtype = r.get("relation_type", "")
        desc = r.get("description", "")
        if not (src and tgt and rtype):
            continue
        out.append(f"{src} --[{rtype}]--> {tgt}" + (f"  ({desc[:80]})" if desc else ""))
    return out


# ---- main entry: 2-tier router --------------------------------------------

async def retrieve_context(query: str, *, top_k: int = 6,
                             intent_hint: str | None = None) -> dict[str, Any]:
    """Unified retrieval v3. Returns {context, citations, low_confidence, debug}.

    intent_hint: optional override from caller (e.g. query_planner). When the
    planner has classified the query's intent (PROCEDURE/EVIDENCE/etc.), the
    act_router's LLM output might still under-include the obvious act for that
    intent — this hint forces the right act in. Deterministic safety net.
    """
    query = (query or "").strip()
    if not query:
        return _build_payload([], low_confidence=True, debug={"tier": "empty_query"})

    # ----- LLM router (single call, memoized) -----
    route = await act_router.route_query(query)

    # Intent-driven act override: PROCEDURE must include BNSS, EVIDENCE must
    # include BSA. The act_router LLM is often too narrow. This is a no-op if
    # the act is already in the list.
    if intent_hint:
        intent_u = intent_hint.upper()
        forced_act: str | None = None
        if intent_u == "PROCEDURE":
            forced_act = "BNSS"
        elif intent_u == "EVIDENCE":
            forced_act = "BSA"
        if forced_act and forced_act not in route["acts"]:
            route = {**route, "acts": [forced_act] + route["acts"]}
        # Stash intent_hint on the route so _semantic_retrieve can branch on it
        route = {**route, "_intent_hint": intent_hint}

    # ----- Tier 1: CITATION LOOKUP (with KG sibling enrichment) -----
    if route["act_explicit"] and route["section_hint"] is not None:
        q_lower = query.lower()
        ordered = [a for a in ("BNSS", "BNS", "BSA")
                   if a.lower() in q_lower and a in route["acts"]]
        if not ordered:
            ordered = list(route["acts"])
        hit = None
        chosen_act = None
        for act in ordered:
            hit = section_lookup.lookup_direct(act, route["section_hint"])
            if hit:
                chosen_act = act
                break
        if hit:
            # C: enrich Tier 1 with KG community siblings
            siblings_raw = legal_lightrag.get_graph().get_section_siblings(
                chosen_act, str(route["section_hint"]), limit=4,
            )
            sibling_records: list[dict[str, Any]] = []
            sibling_meta: list[dict[str, Any]] = []
            for sib in siblings_raw:
                sib_act = sib["act"]
                sib_sec = str(sib["section_number"])
                sib_hit = section_lookup.lookup_direct(sib_act, sib_sec)
                if sib_hit:
                    sibling_records.append(sib_hit)
                    sibling_meta.append({
                        "act": sib_act, "section_number": sib_sec,
                        "via_entity": sib.get("via_entity", ""),
                    })
            hit["related"] = sibling_meta   # attach to main citation
            all_records = [hit] + sibling_records
            return _build_payload(
                all_records,
                low_confidence=False,
                debug={"tier": "1_citation_lookup", "route": route,
                       "matched": f"{chosen_act} {route['section_hint']}",
                       "ordered_acts": ordered,
                       "siblings": [f"{m['act']}§{m['section_number']}" for m in sibling_meta]},
            )

    # ----- Tier 2: UNIFIED SEMANTIC ENGINE -----
    return await _semantic_retrieve(query, top_k=top_k, route=route)


# ---- Tier 2: the unified retriever ----------------------------------------

async def _semantic_retrieve(query: str, *, top_k: int, route: dict[str, Any]) -> dict[str, Any]:
    acts = route["acts"]
    section_hint = route["section_hint"]
    low_kw = route["low_keywords"]
    high_kw = route["high_keywords"]
    sub_queries: list[str] = (route.get("sub_queries") or [query])[:4]
    if not USE_DECOMPOSITION or len(sub_queries) <= 1:
        sub_queries = [query]   # collapse to single-query path

    # --- launch all signals in parallel ---
    # KG runs once (against the original query); sub-queries fan out for vector search.
    kg_task = asyncio.create_task(legal_lightrag.neighbour_sections(
        query, low_keywords=low_kw, high_keywords=high_kw, depth=1, max_entities=15,
    ))

    # HyDE + vector search per sub-query (parallel)
    async def _embed_search(sq: str) -> list[dict[str, Any]]:
        text = await _hyde_expand(sq) if USE_HYDE else sq
        return await search_sections(text, top_k=top_k * VECTOR_OVERFETCH, acts=acts)

    vec_tasks = [asyncio.create_task(_embed_search(sq)) for sq in sub_queries]

    # Await everything
    vec_results = await asyncio.gather(*vec_tasks)
    kg_result = await kg_task

    # Materialise KG sections (LOW + HIGH separately for A)
    low_section_numbers = kg_result.get("low_sections", [])
    high_section_numbers = kg_result.get("high_sections", [])

    async def _fetch_kg_records(section_numbers: list[str]) -> list[dict[str, Any]]:
        records = []
        for sn in section_numbers[: top_k * 2]:
            more = await search_sections("", top_k=1, section_number=sn, acts=acts)
            if more:
                records.append(more[0])
        return records

    low_records, high_records = await asyncio.gather(
        _fetch_kg_records(low_section_numbers),
        _fetch_kg_records(high_section_numbers),
    )

    # Section-hint fallback (router has section number but not act)
    lookup_records: list[dict[str, Any]] = []
    if section_hint is not None:
        lookup_records = section_lookup.lookup_by_number(section_hint, acts)

    # Flatten + collapse vector results (across all sub-queries)
    all_vec = [rec for batch in vec_results for rec in batch]
    seeds = _collapse_by_section(all_vec)[: max(top_k * 3, 18)]

    # Build candidate pool
    pool = _collapse_by_section(seeds + low_records + high_records + lookup_records)

    # BM25 over the pool (boost with all the keywords from all sub-queries)
    bm25_query = " ".join([query] + low_kw + high_kw + sub_queries)
    bm_scored = bm25_search([_doc_for_bm25(r) for r in pool], bm25_query, top_k=top_k * 3)
    bm_ranked = [pool[i]["section_number"] for i, _ in bm_scored]

    # Salience-weighted RRF — LOW + HIGH as SEPARATE streams (A)
    vector_ranked = [r["section_number"] for r in seeds]
    low_ranked = [r["section_number"] for r in low_records]
    high_ranked = [r["section_number"] for r in high_records]
    lookup_ranked = [r["section_number"] for r in lookup_records]

    final_order = _weighted_rrf(
        [
            (vector_ranked,  RRF_WEIGHTS["vector"]),
            (bm_ranked,      RRF_WEIGHTS["bm25"]),
            (low_ranked,     RRF_WEIGHTS["kg_low"]),
            (high_ranked,    RRF_WEIGHTS["kg_high"]),
            (lookup_ranked,  RRF_WEIGHTS["section_lookup"]),
        ],
        top_k=top_k * 3,
    )
    by_number = {r["section_number"]: r for r in pool}
    rrf_top = [by_number[n] for n in final_order if n in by_number]

    # Intent-aware judging thresholds: APPLY_FACTS needs more breadth so the
    # downstream judge LLM (e.g. courtroom) can do real element-matching.
    intent_hint = route.get("_intent_hint", "")
    is_apply_facts = intent_hint.upper() == "APPLY_FACTS"

    # Relevance judge (H3) — drop noise candidates before final rerank
    if USE_RELEVANCE_JUDGE and len(rrf_top) > 6:
        if is_apply_facts:
            rrf_top = await _relevance_judge(
                query, rrf_top, max_keep=15,
                min_keep=APPLY_FACTS_MIN_KEEP,
                min_score=APPLY_FACTS_MIN_SCORE,
            )
        else:
            rrf_top = await _relevance_judge(query, rrf_top, max_keep=12)

    # Element matcher (NEW) — IRAC element-vs-fact check. APPLY_FACTS only.
    # Drops sections whose key elements the case facts don't satisfy (e.g.
    # rejects §316 Breach of Trust when no entrustment present).
    if USE_ELEMENT_MATCHER and is_apply_facts and len(rrf_top) > 3:
        rrf_top = await _element_matcher(query, rrf_top,
                                          min_keep=APPLY_FACTS_MIN_KEEP)

    # Final LLM rerank
    if USE_LLM_RERANK and len(rrf_top) > top_k:
        final = await _llm_rerank(query, rrf_top, take=top_k)
    else:
        final = rrf_top[:top_k]

    best_score = max((r.get("score") or 0.0 for r in final), default=0.0)
    low_conf = (not final) or best_score < LOW_CONFIDENCE_THRESHOLD

    # B: community summaries prepended to context
    community_summaries = kg_result.get("community_summaries", [])
    kg_facts = _kg_facts_from_relationships(kg_result.get("relationships", []))

    return _build_payload(
        final,
        low_confidence=low_conf,
        community_summaries=community_summaries,
        kg_facts=kg_facts,
        debug={
            "tier":             "2_semantic",
            "route":            route,
            "sub_queries":      sub_queries,
            "hyde_enabled":     USE_HYDE,
            "decomp_enabled":   USE_DECOMPOSITION and len(sub_queries) > 1,
            "vector":           vector_ranked,
            "bm25":             bm_ranked,
            "kg_low":           low_ranked,
            "kg_high":          high_ranked,
            "kg_entities":      kg_result.get("entity_names", []),
            "kg_communities":   kg_result.get("community_ids", []),
            "lookup":           lookup_ranked,
            "rrf":              [r["section_number"] for r in rrf_top],
            "final":            [r["section_number"] for r in final],
            "best_score":       best_score,
            "llm_reranked":     USE_LLM_RERANK and len(rrf_top) > top_k,
            "relevance_judged": USE_RELEVANCE_JUDGE,
        },
    )


# ---- LLM rerank (with G — salience tiebreaker) ----------------------------

_RERANK_SYS = (
    "You are a legal-retrieval reranker. Given a user query and N candidate "
    "statute sections, score each 0-10 for how directly it answers the query. "
    "10 = exact answer. 5 = related but not direct. 0 = irrelevant. "
    "Return ONLY JSON: {\"scores\": {\"<section_number>\": <int>, ...}}"
)


async def _llm_rerank(query: str, candidates: list[dict[str, Any]], *, take: int) -> list[dict[str, Any]]:
    try:
        from app.core.llm import get_llm
        llm = get_llm()
        lines = []
        for r in candidates[:20]:
            snippet = (r.get("text") or "")[:300].replace("\n", " ")
            lines.append(
                f"[{r['section_number']}] {r['act']} §{r['section_number']} "
                f"{r['section_title']}: {snippet}"
            )
        user_msg = f"QUERY: {query}\n\nCANDIDATES:\n" + "\n".join(lines)
        data = await llm.complete_json(
            [
                {"role": "system", "content": _RERANK_SYS},
                {"role": "user",   "content": user_msg},
            ],
            fast=True,
            max_tokens=1500,
            temperature=0.0,
        )
        scores = data.get("scores") or {}

        def _llm_score(r: dict[str, Any]) -> int:
            try: return int(scores.get(str(r.get("section_number") or ""), 0))
            except Exception: return 0

        # G: salience tiebreaker — when LLM ties, prefer sections whose primary
        # entity has higher salience (we use Pinecone score as a proxy here
        # since we don't have entity-salience per Pinecone result; tweak later
        # if we add it to metadata).
        def _sort_key(r: dict[str, Any]) -> tuple:
            llm = _llm_score(r)
            vec_score = r.get("score") or 0.0
            return (-llm, -vec_score, candidates.index(r))

        ranked = sorted(candidates, key=_sort_key)
        kept = [r for r in ranked if _llm_score(r) >= RERANK_MIN_SCORE]
        if len(kept) < RERANK_MIN_RESULTS:
            kept = ranked[:RERANK_MIN_RESULTS]
        cap = min(take, RERANK_MAX_RESULTS, len(kept))
        return kept[:cap]
    except Exception:
        return candidates[:take]
