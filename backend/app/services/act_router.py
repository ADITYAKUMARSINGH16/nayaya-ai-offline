"""LLM-only query router (no regex parsing of user text).

v2 design (matches "really good RAG" plan, item M + bug-2a fix):

  - The LLM router is the sole source of section_hint, acts, and keywords.
    No regex back-fills. If the LLM call fails completely, we default to
    "all acts, no section hint, no keywords" — a safe fall-through that
    routes everything to the unified semantic engine.
  - Memoized per query (LRU on lowercased query). Same input → same output,
    fixes the non-determinism bug.
  - Prompt explicitly says: DO NOT treat dates (e.g. "20 March 2026"), ages
    ("17 years"), or amounts ("1,20,000 rupees") as section numbers.
  - Output now includes low_keywords + high_keywords for the two-level LightRAG
    retrieval, eliminating the need for a separate dual-level-keywords pass.

Schema returned by route_query():

  {
    "acts":         ["BNS"] | ["BNSS"] | ["BSA"] | combo,
    "intent":       "lookup" | "concept" | "procedure" | "evidence",
    "section_hint": int | None,
    "act_explicit": bool,                  # true ONLY if user typed an act name
    "confidence":   "high" | "medium" | "low",
    "low_keywords": [str],                 # 1-5 concrete terms
    "high_keywords":[str],                 # 1-3 abstract themes
  }
"""
from __future__ import annotations

import asyncio
import logging
from functools import lru_cache
from typing import Any

log = logging.getLogger(__name__)

_VALID_ACTS = {"BNS", "BNSS", "BSA"}
_VALID_INTENTS = {"lookup", "concept", "procedure", "evidence"}
_VALID_CONFIDENCE = {"high", "medium", "low"}

_ROUTER_SYS = """You route Indian legal queries.

THREE ACTS:
  BNS  (Bharatiya Nyaya Sanhita 2023)        — substantive criminal law: offences,
       definitions, punishments. Replaces IPC.
  BNSS (Bharatiya Nagarik Suraksha Sanhita)  — procedure: FIR, arrest, bail,
       investigation, custody, trial, charge sheet, summons, warrant, search.
       Replaces CrPC.
  BSA  (Bharatiya Sakshya Adhiniyam 2023)    — evidence: admissibility, witness,
       documents, presumptions, burden of proof, confession. Replaces IEA.

Return ONLY JSON in this exact shape:
{
  "acts": ["BNS"],
  "intent": "lookup",
  "section_hint": 202,
  "act_explicit": true,
  "confidence": "high",
  "low_keywords": ["public servant", "trade"],
  "high_keywords": ["public-servant offences"],
  "sub_queries": ["public servant unlawfully engaging in trade"]
}

RULES:

R1. section_hint = ONLY set to an integer if the user EXPLICITLY referenced a
    section (e.g. "section 202", "BNS 202", "s. 303", "sec. 35").
    NEVER extract a section number from:
      - dates ("20 March 2026", "12 January")
      - ages ("17 years old", "child under 7")
      - amounts ("Rs 1,20,000", "fine of 500")
      - statute citations to OTHER acts ("section 5 of IT Act 2000")
      - general numbers in narrative text
    If unsure, set section_hint to null.

R2. act_explicit = true ONLY if the user TYPED an act name ("BNS", "BNSS",
    "BSA", "Bharatiya Nyaya Sanhita", "Indian Penal Code" → BNS, etc.).
    Inferring an act from context is NOT explicit.

R3. acts = list of relevant acts. Default to all three at "low" confidence
    if truly unsure. Over-include rather than miss.

R4. intent = lookup (specific section text), concept (what does law say
    about X), procedure (how do I do X legally), evidence (admissibility).

R5. low_keywords = 1-5 concrete legal terms a user might search by.
    high_keywords = 1-3 abstract themes / categories.
    For "what's the punishment for theft":
      low = ["theft", "punishment for theft"]
      high = ["property crimes"]
    For long case facts (a paragraph), focus on the OFFENCE and the legal
    issue, NOT the people/places/times.

R6. sub_queries = if the user's query is COMPOUND (asks about multiple distinct
    legal aspects), decompose into 2-4 focused sub-queries. Each sub-query
    should be a self-contained natural-language question.
    Examples:
      "my friend was arrested for theft, what next" →
        sub_queries = [
          "what is the offence of theft",
          "what is the procedure after arrest",
          "what are the bail rights of an accused"
        ]
      "is hearsay admissible as evidence" → sub_queries = ["is hearsay admissible as evidence"]  (single-aspect → just the query itself)
      "BNS 202" → sub_queries = ["BNS 202"]  (citation lookup, no decomposition needed)
    Default: a list with just the original query if no decomposition makes sense.

R7. Output JSON only. No prose, no markdown."""


def _coerce(data: dict[str, Any]) -> dict[str, Any]:
    """Validate + normalise the LLM's JSON. Safe defaults for missing fields."""
    acts_raw = data.get("acts") or []
    if isinstance(acts_raw, str):
        acts_raw = [acts_raw]
    acts = []
    seen = set()
    for a in acts_raw:
        if not isinstance(a, str):
            continue
        u = a.strip().upper()
        if u in _VALID_ACTS and u not in seen:
            seen.add(u)
            acts.append(u)
    if not acts:
        acts = ["BNS", "BNSS", "BSA"]

    intent = str(data.get("intent") or "").strip().lower()
    if intent not in _VALID_INTENTS:
        intent = "concept"

    section_hint = data.get("section_hint")
    if isinstance(section_hint, str):
        section_hint = section_hint.strip()
        section_hint = int(section_hint) if section_hint.isdigit() else None
    if not isinstance(section_hint, int) or section_hint <= 0 or section_hint > 600:
        section_hint = None

    act_explicit = bool(data.get("act_explicit", False))

    confidence = str(data.get("confidence") or "").strip().lower()
    if confidence not in _VALID_CONFIDENCE:
        confidence = "medium"

    def _str_list(k: str, cap: int) -> list[str]:
        raw = data.get(k) or []
        if isinstance(raw, str):
            raw = [raw]
        out: list[str] = []
        seen: set[str] = set()
        for x in raw:
            if not isinstance(x, str):
                continue
            v = x.strip()
            if v and v.lower() not in seen:
                seen.add(v.lower())
                out.append(v)
            if len(out) >= cap:
                break
        return out

    return {
        "acts":          acts,
        "intent":        intent,
        "section_hint":  section_hint,
        "act_explicit":  act_explicit,
        "confidence":    confidence,
        "low_keywords":  _str_list("low_keywords", 5),
        "high_keywords": _str_list("high_keywords", 3),
        "sub_queries":   _str_list("sub_queries", 4),
    }


_SAFE_DEFAULT = {
    "acts":          ["BNS", "BNSS", "BSA"],
    "intent":        "concept",
    "section_hint":  None,
    "act_explicit":  False,
    "confidence":    "low",
    "low_keywords":  [],
    "high_keywords": [],
    "sub_queries":   [],
}


# In-memory LRU memoization (item M). Per-process; resets when the worker dies.
_router_cache: dict[str, dict[str, Any]] = {}
_router_lock = asyncio.Lock()
_CACHE_MAX = 2048


async def route_query(query: str) -> dict[str, Any]:
    """LLM-only router with memoization. Returns the schema above.

    On any LLM error: returns _SAFE_DEFAULT (no regex back-fills). The semantic
    engine handles low-confidence routing gracefully.
    """
    q = (query or "").strip()
    if not q:
        return dict(_SAFE_DEFAULT)

    key = q.lower()[:500]
    # Fast path — memo hit
    if key in _router_cache:
        return dict(_router_cache[key])

    try:
        from app.core.llm import get_llm
        llm = get_llm()
        data = await llm.complete_json(
            [
                {"role": "system", "content": _ROUTER_SYS},
                {"role": "user", "content": q[:1500]},   # bumped — accept longer queries
            ],
            fast=True,
            temperature=0.0,
            max_tokens=800,
        )
        result = _coerce(data)
    except Exception as exc:
        log.warning("act_router LLM call failed; using safe default: %s", exc)
        result = dict(_SAFE_DEFAULT)

    # Cache with simple bound
    async with _router_lock:
        if len(_router_cache) >= _CACHE_MAX:
            _router_cache.clear()
        _router_cache[key] = dict(result)

    return result


def clear_cache() -> None:
    """For tests / admin endpoints."""
    _router_cache.clear()
