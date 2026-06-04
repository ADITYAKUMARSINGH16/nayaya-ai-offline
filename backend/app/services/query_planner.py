"""LLM query planner — the agentic upgrade over the stateless act_router.

Architecture (plan → execute → reflect → synthesize):

  User query (+ recent chat history)
        │
        ▼
  ┌─────────────────────────────────────────────────────────────────────┐
  │ STEP 1: PLAN                                                        │
  │   One LLM call returns a typed plan:                                │
  │     - intent        : LOOKUP | EXPLAIN | APPLY_FACTS | PROCEDURE | │
  │                       ADVISE | COMPARE | FOLLOWUP                  │
  │     - rewritten_query : coreference-resolved, made standalone       │
  │     - sub_queries   : 1-4 self-contained sub-queries with intent +  │
  │                       expected-answer-shape per sub-query           │
  │     - synthesis     : how to compose the final answer               │
  └─────────────────────────────────────────────────────────────────────┘
        │
        ▼
  ┌─────────────────────────────────────────────────────────────────────┐
  │ STEP 2: EXECUTE — each sub-query goes through retrieve_context      │
  │   (which itself runs HyDE + decomp + KG + RRF + relevance judge).   │
  └─────────────────────────────────────────────────────────────────────┘
        │
        ▼
  ┌─────────────────────────────────────────────────────────────────────┐
  │ STEP 3: REFLECT — one LLM call judges each sub-query result:        │
  │   { quality: 0-1, missing: "what's still unanswered", retry: bool, │
  │     refined_query: optional rewrite if retry }                      │
  │   If retry: re-run that sub-query (capped at 1 retry).              │
  └─────────────────────────────────────────────────────────────────────┘
        │
        ▼
  ┌─────────────────────────────────────────────────────────────────────┐
  │ STEP 4: SYNTHESIZE — one LLM call composes the final answer using   │
  │   all sub-query results. Output includes:                           │
  │     - answer text                                                   │
  │     - citation_provenance: maps each ANSWER paragraph to which      │
  │       sub-query/citation supports it                                │
  │     - confidence                                                    │
  └─────────────────────────────────────────────────────────────────────┘

Cost per query: 2 + N (sub-queries) + N (reflect) + 0-N (retry) + 1 (synth)
             ≈ 5-10 LLM calls. Real legal-assistant cost is in the answer
             quality, not the LLM count.
Latency: ~10-15 sec per query. Acceptable for a careful legal assistant.

This module ONLY powers the chat assistant. FIR / police / courtroom agents
keep calling retrieve_context directly — their case-facts inputs go through
the same Tier 2 pipeline but don't need the planner's plan-and-reflect loop
since they have well-defined output schemas already.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.services.rag import retrieve_context

log = logging.getLogger(__name__)


# ---- typed schema ---------------------------------------------------------

VALID_INTENTS = {
    "LOOKUP",      # user wants the text of a specific section
    "EXPLAIN",     # user wants conceptual explanation of a legal idea
    "APPLY_FACTS", # user describes a scenario, wants to know what applies
    "PROCEDURE",   # how to do something (file FIR, get bail, etc.)
    "ADVISE",      # what should they do; multi-step recommendation
    "COMPARE",     # compare two things (e.g., theft vs robbery)
    "FOLLOWUP",    # depends on prior conversation context
}


@dataclass
class SubQuery:
    id: str
    query: str
    intent: str
    expected: str = ""                # what the answer should contain
    # When intent=LOOKUP and the planner LLM is confident, it emits these so
    # the executor can bypass act_router/retrieve_context and call
    # section_lookup directly. Removes the non-determinism of routing for
    # explicit citation queries like "BNS 202".
    lookup_act: str | None = None
    lookup_section: int | None = None
    result: dict[str, Any] | None = None
    quality: float = 0.0              # 0-1 from reflector
    missing: str = ""                 # what's still unanswered
    retry_count: int = 0
    refined_query: str | None = None


@dataclass
class QueryPlan:
    plan_id: str
    user_query: str
    rewritten_query: str              # coreference-resolved standalone form
    intent: str
    sub_queries: list[SubQuery] = field(default_factory=list)
    synthesis_template: str = ""      # how to compose the answer


@dataclass
class PlanResult:
    plan: QueryPlan
    answer: str
    citations: list[dict[str, Any]] = field(default_factory=list)
    provenance: dict[str, list[str]] = field(default_factory=dict)
    confidence: str = "medium"
    low_confidence: bool = False
    debug: dict[str, Any] = field(default_factory=dict)


# ---- STEP 1: PLAN ---------------------------------------------------------

_PLANNER_SYS = """You plan how to answer an Indian-legal question by breaking
it into sub-queries that a retrieval engine can answer.

The retrieval engine covers ONLY:
  - BNS  (Bharatiya Nyaya Sanhita 2023)        — substantive criminal law
  - BNSS (Bharatiya Nagarik Suraksha Sanhita)  — criminal procedure
  - BSA  (Bharatiya Sakshya Adhiniyam 2023)    — evidence

CRITICAL — DO NOT mention or reference the OLD acts in rewritten_query or
sub_queries:
  - NEVER write "IPC" or "Indian Penal Code"          → use BNS instead
  - NEVER write "CrPC" or "Code of Criminal Procedure" → use BNSS instead
  - NEVER write "IEA" or "Indian Evidence Act"        → use BSA instead
Even if the user asks about IPC, silently translate to BNS. The retrieval
corpus has no IPC/CrPC/IEA content, so any reference to them is a query
poisoning bug.

CRITICAL — DO NOT add act names to sub_queries UNLESS the user explicitly
typed them. The retrieval engine has its own act router. Adding "under BNS"
to a procedural sub-query forces retrieval into the wrong act.
  - "my friend was arrested for theft, what next"  → sub-queries like
        "what happens after an arrest"  (no act name — let router decide BNSS)
        "what is theft"                 (no act name — router picks BNS)
        "what are bail rights"          (no act name — router picks BNSS)
  - "BNS 202" → keep "BNS 202" (user typed the act, it's explicit)

Default rule: KEEP SUB-QUERIES ACT-AGNOSTIC unless the user named an act.

Return ONLY JSON:
{
  "rewritten_query": "<the user's query, made standalone — resolve any 'it/this/the punishment' coreferences using chat history>",
  "intent": "<one of: LOOKUP | EXPLAIN | APPLY_FACTS | PROCEDURE | ADVISE | COMPARE | FOLLOWUP>",
  "sub_queries": [
    {
      "query":          "<self-contained natural-language question>",
      "intent":         "<same enum as above>",
      "expected":       "<one phrase describing what a good answer would contain>",
      "lookup_act":     "<BNS | BNSS | BSA or null — set ONLY when sub-query is a citation lookup for a specific section in that act>",
      "lookup_section": "<integer section number or null — must accompany lookup_act>"
    }
  ],
  "synthesis_template": "<short instruction for how to compose the final answer>"
}

RULES:

R1. INTENTS — pick the single most accurate:
    - LOOKUP: user named a specific section ("BNS 202", "section 303")
    - EXPLAIN: user asks WHAT a legal concept is ("what is theft", "define dishonest")
    - APPLY_FACTS: user describes a scenario, asking what law applies
       ("On 20 March X took Y's phone — what offences?")
    - PROCEDURE: HOW to do something legally ("how to file an FIR", "how to get bail")
    - ADVISE: multi-step what-to-do recommendation ("my friend was arrested, what now")
    - COMPARE: compare two things ("difference between theft and robbery")
    - FOLLOWUP: query only makes sense given prior chat turn

R2. SUB-QUERY DECOMPOSITION — keep it minimal AND faithful:
    - Single-aspect queries → 1 sub-query = the user's rewritten query VERBATIM.
      DO NOT rephrase, shorten, or generalise. If user asks "what is the
      punishment for theft", the sub-query MUST contain BOTH "punishment"
      AND "theft". Never silently drop the key concern.
    - Compound queries → 2-4 focused sub-queries, each preserving the key
      noun/verb from its part of the original.
    - Anti-example (do not do this):
        User: "what is the punishment for theft"
        BAD sub-query: "what is theft under BNS"    ← dropped "punishment" + added act
        GOOD sub-query: "what is the punishment for theft"   ← faithful
    - Example decompositions:
        "my friend was arrested for theft, what next" →
          [{"query": "what is theft under BNS", "intent": "EXPLAIN", "lookup_act": null, "lookup_section": null, ...},
           {"query": "what is the procedure after arrest", "intent": "PROCEDURE", "lookup_act": null, "lookup_section": null, ...},
           {"query": "what are the bail rights of an arrested person", "intent": "PROCEDURE", "lookup_act": null, "lookup_section": null, ...}]
        "BNS 202" →
          [{"query": "BNS 202", "intent": "LOOKUP", "expected": "text of BNS section 202",
            "lookup_act": "BNS", "lookup_section": 202}]
        "BSA 119" →
          [{"query": "BSA 119", "intent": "LOOKUP", "expected": "text of BSA section 119",
            "lookup_act": "BSA", "lookup_section": 119}]
        "section 303" → (no explicit act named — let executor figure it out)
          [{"query": "section 303", "intent": "LOOKUP", "expected": "section 303 of the most relevant act",
            "lookup_act": null, "lookup_section": null}]
        "difference between theft and robbery" →
          [{"query": "what is theft under BNS", "intent": "EXPLAIN", ...},
           {"query": "what is robbery under BNS", "intent": "EXPLAIN", ...}]

    LOOKUP_ACT and LOOKUP_SECTION: Set BOTH only when the user EXPLICITLY
    named an act (BNS/BNSS/BSA, or full names like Bharatiya Nyaya Sanhita)
    AND named a numeric section. Otherwise leave both null.

R3. COREFERENCE — if chat history is provided and the query has unresolved
    references ("the punishment", "what about that", "is it admissible"),
    rewrite into a STANDALONE query using prior context. Otherwise return the
    query unchanged.

R4. EXPECTED — one short phrase per sub-query describing what answer text
    should look like. Used by the reflector to judge quality.

R5. SYNTHESIS — one instruction for how to compose the final answer. For
    APPLY_FACTS, often: "list applicable offences with their sections, then
    state punishments, then next-steps". For LOOKUP: "concise restatement of
    the section with citation". Etc.

R6. Output JSON only. No prose, no markdown."""


async def _plan(user_query: str, history: list[dict] | None = None) -> QueryPlan:
    from app.core.llm import get_llm
    llm = get_llm()
    history_text = ""
    if history:
        # Last 6 turns max — keep prompt tight
        turns = []
        for r in history[-6:]:
            role = "Assistant" if r.get("role") == "assistant" else "User"
            msg = (r.get("message") or "").strip().replace("\n", " ")
            if msg:
                turns.append(f"{role}: {msg[:200]}")
        history_text = "\n".join(turns)

    user_msg = (
        (f"CHAT HISTORY (recent turns):\n{history_text}\n\n" if history_text else "")
        + f"USER QUERY: {user_query[:600]}"
    )

    try:
        data = await llm.complete_json(
            [
                {"role": "system", "content": _PLANNER_SYS},
                {"role": "user",   "content": user_msg},
            ],
            fast=True,
            temperature=0.0,
            max_tokens=2000,
        )
    except Exception as exc:
        log.warning("planner LLM call failed: %s — using single-query fallback", exc)
        return _fallback_plan(user_query)

    return _coerce_plan(data, user_query)


def _coerce_plan(data: dict[str, Any], user_query: str) -> QueryPlan:
    rewritten = str(data.get("rewritten_query") or user_query).strip() or user_query
    intent = str(data.get("intent") or "").strip().upper()
    if intent not in VALID_INTENTS:
        intent = "EXPLAIN"

    sub_qs_raw = data.get("sub_queries") or []
    sub_queries: list[SubQuery] = []
    for sq in sub_qs_raw[:4]:
        if not isinstance(sq, dict):
            continue
        q = str(sq.get("query", "")).strip()
        if not q:
            continue
        si = str(sq.get("intent", "")).strip().upper()
        if si not in VALID_INTENTS:
            si = intent
        expected = str(sq.get("expected", "")).strip()
        # Validate lookup_act/lookup_section: both must be present and valid
        la_raw = sq.get("lookup_act")
        ls_raw = sq.get("lookup_section")
        lookup_act = None
        lookup_section = None
        if isinstance(la_raw, str) and la_raw.strip().upper() in {"BNS", "BNSS", "BSA"}:
            lookup_act = la_raw.strip().upper()
        try:
            if ls_raw is not None and (isinstance(ls_raw, int) or
                                         (isinstance(ls_raw, str) and ls_raw.strip().isdigit())):
                n = int(ls_raw) if not isinstance(ls_raw, int) else ls_raw
                if 1 <= n <= 600:
                    lookup_section = n
        except (ValueError, TypeError):
            pass
        # Only commit lookup if BOTH set
        if lookup_act is None or lookup_section is None:
            lookup_act = None
            lookup_section = None
        sub_queries.append(SubQuery(
            id=uuid.uuid4().hex[:8],
            query=q,
            intent=si,
            expected=expected,
            lookup_act=lookup_act,
            lookup_section=lookup_section,
        ))
    if not sub_queries:
        sub_queries = [SubQuery(id=uuid.uuid4().hex[:8], query=rewritten, intent=intent)]

    return QueryPlan(
        plan_id=uuid.uuid4().hex[:8],
        user_query=user_query,
        rewritten_query=rewritten,
        intent=intent,
        sub_queries=sub_queries,
        synthesis_template=str(data.get("synthesis_template", "")).strip(),
    )


def _fallback_plan(user_query: str) -> QueryPlan:
    """LLM failed → single sub-query, treat as EXPLAIN by default."""
    return QueryPlan(
        plan_id=uuid.uuid4().hex[:8],
        user_query=user_query,
        rewritten_query=user_query,
        intent="EXPLAIN",
        sub_queries=[SubQuery(id=uuid.uuid4().hex[:8], query=user_query, intent="EXPLAIN")],
        synthesis_template="answer in 1-2 paragraphs with citations",
    )


# ---- STEP 2: EXECUTE ------------------------------------------------------

async def _execute_sub_query(sq: SubQuery, *, top_k: int = 6) -> None:
    """Run a single sub-query, mutating sq.result.

    SHORTCUT: when sq.lookup_act + lookup_section are set (planner identified an
    explicit citation), call section_lookup + sibling enrichment directly. This
    is faster and 100% deterministic — no act_router non-determinism risk.

    Otherwise, fall through to the full retrieve_context pipeline.
    """
    if sq.lookup_act and sq.lookup_section is not None:
        try:
            from app.services import section_lookup, legal_lightrag
            main = section_lookup.lookup_direct(sq.lookup_act, sq.lookup_section)
            if main:
                # Sibling enrichment via KG
                siblings_raw = legal_lightrag.get_graph().get_section_siblings(
                    sq.lookup_act, str(sq.lookup_section), limit=4,
                )
                sibling_records = []
                sibling_meta = []
                for sib in siblings_raw:
                    sib_hit = section_lookup.lookup_direct(sib["act"], sib["section_number"])
                    if sib_hit:
                        sibling_records.append(sib_hit)
                        sibling_meta.append({
                            "act": sib["act"],
                            "section_number": sib["section_number"],
                            "via_entity": sib.get("via_entity", ""),
                        })
                main["related"] = sibling_meta
                all_records = [main] + sibling_records
                from app.services.rag import _to_text_citation
                blocks: list[str] = []
                citations: list[dict[str, Any]] = []
                for rec in all_records:
                    b, c = _to_text_citation(rec)
                    blocks.append(b)
                    citations.append(c)
                sq.result = {
                    "context":        "\n\n".join(blocks),
                    "citations":      citations,
                    "low_confidence": False,
                    "debug":          {"tier": "planner_direct_lookup",
                                       "matched": f"{sq.lookup_act} {sq.lookup_section}",
                                       "siblings": [f"{m['act']}§{m['section_number']}" for m in sibling_meta]},
                }
                return
            # If direct lookup missed (rare), fall through to retrieve_context
            log.warning("planner direct lookup miss for %s %s; falling through",
                         sq.lookup_act, sq.lookup_section)
        except Exception as exc:
            log.warning("planner direct lookup failed: %s — falling through to retrieve_context", exc)

    # Normal path: full retrieve_context pipeline, passing intent as a hint
    # so the act_router can be overridden for PROCEDURE/EVIDENCE queries.
    try:
        sq.result = await retrieve_context(sq.query, top_k=top_k, intent_hint=sq.intent)
    except Exception as exc:
        log.warning("sub-query %s failed: %s", sq.id, exc)
        sq.result = {"context": "", "citations": [], "low_confidence": True,
                      "debug": {"error": str(exc)}}


# ---- STEP 3: REFLECT ------------------------------------------------------

_REFLECT_SYS = """You judge whether a retrieval result actually answers a
sub-query. BE GENEROUS — the retrieval pipeline is sophisticated and most
results are useful even if not perfect.

Inputs you'll receive:
  - SUB_QUERY: the question we tried to retrieve for
  - EXPECTED: what a good answer should contain
  - CITATIONS: the sections that came back
  - LOW_CONFIDENCE: whether the retriever flagged low confidence

Return ONLY JSON:
{
  "quality":       <0.0 - 1.0>,
  "missing":       "<one short phrase, or empty string>",
  "should_retry":  <true | false>,
  "refined_query": "<rewritten query for the retry, or null if no retry>"
}

QUALITY RUBRIC (be generous — default to 0.7 unless clearly wrong):

  1.0   = LOOKUP query and the exact section appears in citations
          (e.g. SUB_QUERY="BNS 202" and citations contain BNS§202)
  0.85  = EXPLAIN/PROCEDURE/etc and the most-relevant section for that topic
          appears in the top citations (e.g. "punishment for theft" → BNS§303
          in citations even if not first)
  0.7   = Citations are from the right act AND contain at least one section
          whose title matches the sub-query topic. THIS IS THE DEFAULT for
          plausible results.
  0.5   = Citations are mixed — some relevant, some not. Or right topic but
          wrong specific section.
  0.3   = Citations are from the wrong act for the question, or all citations
          are tangential.
  0.0   = No citations, or citations are completely unrelated.

DO NOT penalize for:
  - Extra citations beyond the main answer (siblings/related sections add
    value, not noise)
  - Non-canonical phrasings in citation titles
  - LOW_CONFIDENCE flag (it's often a false alarm for valid niche queries)

SHOULD_RETRY only if quality < 0.5 AND you can write a clearly different
query that would do better. If you'd just rephrase the same words, don't retry.

REFINED_QUERY rules (CRITICAL):
  - NEVER mention "IPC", "Indian Penal Code", "CrPC", "Code of Criminal
    Procedure", "IEA", or "Indian Evidence Act". Use BNS / BNSS / BSA only.
  - Keep the same language register as the original.
"""


async def _reflect(sq: SubQuery) -> None:
    """Score a sub-query's result. Mutates sq.quality / sq.missing / sq.refined_query."""
    if not sq.result:
        sq.quality = 0.0
        sq.missing = "no result"
        return

    cites = sq.result.get("citations", []) or []
    cites_str = ", ".join(
        f"{c.get('act','')}§{c.get('section_number','')} ({c.get('section_title','')[:40]})"
        for c in cites[:5]
    ) or "(no citations)"

    user_msg = (
        f"SUB_QUERY: {sq.query}\n"
        f"INTENT: {sq.intent}\n"
        f"EXPECTED: {sq.expected or '(unspecified)'}\n"
        f"CITATIONS: {cites_str}\n"
        f"LOW_CONFIDENCE: {sq.result.get('low_confidence', False)}\n"
    )

    try:
        from app.core.llm import get_llm
        llm = get_llm()
        data = await llm.complete_json(
            [
                {"role": "system", "content": _REFLECT_SYS},
                {"role": "user",   "content": user_msg},
            ],
            fast=True,
            temperature=0.0,
            max_tokens=500,
        )
        try:
            sq.quality = float(data.get("quality", 0.5))
        except (ValueError, TypeError):
            sq.quality = 0.5
        sq.quality = max(0.0, min(1.0, sq.quality))
        sq.missing = str(data.get("missing", "")).strip()
        if data.get("should_retry") and data.get("refined_query") and sq.retry_count < 1:
            rq = str(data["refined_query"]).strip()
            if rq and rq.lower() != sq.query.lower():
                sq.refined_query = rq
    except Exception as exc:
        log.warning("reflect failed for %s: %s", sq.id, exc)
        # Default: assume OK if we got results
        sq.quality = 0.7 if cites else 0.3


# ---- STEP 4: SYNTHESIZE ---------------------------------------------------

_SYNTH_SYS = """You are Nyaya Sahayak, an expert in Indian criminal law.
Compose a clear, accurate answer to the user's ORIGINAL question by
integrating the retrieved sub-query results.

THE ACTS — use these EXACT names; never confabulate:
  - BNS  = Bharatiya Nyaya Sanhita, 2023        (NOT "Standard", NOT "Samhita")
  - BNSS = Bharatiya Nagarik Suraksha Sanhita, 2023
  - BSA  = Bharatiya Sakshya Adhiniyam, 2023

CRITICAL RULES (statute compliance):
1. CITE ONLY BNS 2023, BNSS 2023, or BSA 2023 — NEVER write "IPC", "Indian
   Penal Code", "CrPC", "Code of Criminal Procedure", "IEA", or "Indian
   Evidence Act" anywhere in the answer. Not even in meta-commentary like
   "BNS replaces IPC" or "unlike the old CrPC". Simply present BNS/BNSS/BSA
   as THE law. The Indian legal world moved on — your answer reflects that.
2. EVERY substantive claim must be tied to a specific section from the
   provided citations. Don't make up sections.
3. If the retrieved sections don't answer the question, say so plainly.
4. NEVER write internal taxonomy tags in the answer:
   - DO NOT write "(LOOKUP)", "(EXPLAIN)", "(PROCEDURE)" etc.
   - DO NOT write headers like "Sub-query 1:", "Definition pursuit:"
   - DO NOT mention "the retrieval result" or "the citations show".
   Just write the answer as if it's coming from a confident legal expert.

CITATION FIELDS (each context block may contain these labeled fields):
   - "Summary: ..." — pre-extracted one-sentence summary from the corpus
   - "Punishment: ..." — pre-extracted punishment text in canonical form
   - "Text: ..." — the section's raw statute text (may be truncated)

   These fields are AUTHORITATIVE. They were extracted from the source
   sections by a structured pipeline.

   - When the user asks about PUNISHMENT, USE the `Punishment:` field of
     the most-relevant section DIRECTLY. Do NOT search the Text field for
     the punishment if a Punishment field is present.
   - NEVER say "no standalone punishment is given" or "the punishment isn't
     specified" if any cited section has a non-null Punishment field.
   - For "punishment for X" queries, the canonical answer cites the section
     whose Punishment field most directly matches X. That section is usually
     the FOUNDATIONAL section for X (e.g. for "punishment for theft" → the
     section literally titled "Theft" or where theft is defined, NOT a
     section about a related offence that happens to mention theft).

ANSWER STYLE:
- Conversational, lawyer-precise prose. 1-3 short paragraphs.
- Use **bold** for section references like **BNS §303**.
- Open directly with the substantive answer — no preamble like "Here is".
- For LOOKUP queries: concise restatement of the section's rule and any
  punishment. State the section number naturally in prose.
- For EXPLAIN queries: define the concept, cite the defining section.
- For APPLY_FACTS / ADVISE queries: identify the offence(s), state the law,
  then a "**Next steps:**" mini-list at the end.
- For COMPARE queries: brief side-by-side.

WHICH CITATION TO LEAD WITH:
- When asked about a concept (e.g. "theft", "robbery"), lead with the
  FOUNDATIONAL/DEFINING section (usually the LOWEST-NUMBERED section in the
  chapter, since statutes put the base offence first and variants after).
  Example: for "punishment for theft" lead with **BNS §303** (defines theft
  and sets base punishment), THEN mention §305 (theft in specific places),
  §306 (theft by clerk), §307 (theft after preparation) as variants if relevant.
- When asked "what to do", lead with the procedural section the user would
  actually invoke first.
- When asked to compare, lead with whichever section comes first in the
  comparison naturally.

Return ONLY JSON:
{
  "answer":     "<the full answer markdown — clean prose, no tags>",
  "confidence": "high" | "medium" | "low",
  "provenance": {
    "<short paragraph label>": ["<act>§<num>", "<act>§<num>"]
  }
}

CONFIDENCE CALIBRATION (don't be falsely modest):
  high   = You have ≥2 cited sections and can directly quote the relevant
           statute text in your answer. DEFAULT to this when retrieval gave
           you usable citations.
  medium = You can answer but with caveats — e.g. sections cover the topic
           but not the exact aspect asked, or you can only partially answer.
  low    = You genuinely lack the information to answer the question.

provenance: 2-4 entries max, each key is a 2-5-word descriptor of one part
of the answer (e.g. "definition of theft", "applicable punishment", "next steps").
"""


def _reorder_context_for_synth(sub_query: str, intent: str, context: str) -> str:
    """When intent is conceptual (EXPLAIN/APPLY_FACTS/etc.), pre-sort the
    sections in the context block so the FOUNDATIONAL section (lowest-
    numbered + has a Punishment field that matches the query) appears first.

    The synth LLM reads positionally — even though we tell it to lead with the
    foundational section, it tends to follow input order. So we bias the order.
    """
    if intent in {"LOOKUP", "PROCEDURE"}:
        return context  # don't reorder these — the retriever's order is right

    # Parse the context into blocks (separated by blank lines)
    blocks = context.split("\n\n")
    parsed: list[tuple[int, str]] = []   # (sort_key, block)
    other: list[str] = []
    for b in blocks:
        if not b.strip():
            continue
        # Try to extract section_number from "ACT Section N: title" header
        first_line = b.split("\n", 1)[0]
        try:
            section_num = int(first_line.split("Section", 1)[1].split(":", 1)[0].strip())
        except (IndexError, ValueError):
            other.append(b)
            continue
        # Has Punishment field? prioritize
        has_punishment = "Punishment:" in b
        # Sort key: punishment-having blocks first, then by section number ascending
        sort_key = (0 if has_punishment else 1, section_num)
        parsed.append((sort_key, b))

    parsed.sort(key=lambda x: x[0])
    reordered = [b for _, b in parsed] + other
    return "\n\n".join(reordered)


async def _synthesize(plan: QueryPlan) -> tuple[str, dict[str, list[str]], str]:
    """Compose final answer from per-sub-query results. Returns (answer, provenance, confidence)."""
    # Build the context block: per-sub-query, list its citations + context snippet
    parts: list[str] = []
    parts.append(f"USER QUERY: {plan.user_query}")
    if plan.rewritten_query != plan.user_query:
        parts.append(f"REWRITTEN: {plan.rewritten_query}")
    parts.append(f"INTENT: {plan.intent}")
    if plan.synthesis_template:
        parts.append(f"SYNTHESIS NOTE: {plan.synthesis_template}")
    parts.append("")

    for i, sq in enumerate(plan.sub_queries, 1):
        parts.append(f"=== SUB-QUERY {i}: {sq.query} (intent={sq.intent}, quality={sq.quality:.2f}) ===")
        if sq.expected:
            parts.append(f"  expected: {sq.expected}")
        if not sq.result:
            parts.append("  (no result)")
            continue
        # No truncation — full context goes to synth. User has budget.
        raw_ctx = (sq.result.get("context") or "")
        ctx = _reorder_context_for_synth(sq.query, sq.intent, raw_ctx)
        if ctx:
            parts.append("  CONTEXT:")
            parts.append("  " + ctx.replace("\n", "\n  "))
        if sq.missing:
            parts.append(f"  GAP: {sq.missing}")
    full = "\n".join(parts)

    try:
        from app.core.llm import get_llm
        llm = get_llm()
        data = await llm.complete_json(
            [
                {"role": "system", "content": _SYNTH_SYS},
                {"role": "user",   "content": full},
            ],
            temperature=0.2,
            # No max_tokens — let the answer be as long as the LLM thinks
            # is needed. Inherits the 8000 default from base.py.
        )
        answer = str(data.get("answer", "")).strip()
        prov = data.get("provenance") or {}
        prov_clean: dict[str, list[str]] = {}
        if isinstance(prov, dict):
            for k, v in prov.items():
                if isinstance(v, list):
                    prov_clean[str(k)[:60]] = [str(x) for x in v[:6]]
        conf = str(data.get("confidence", "medium")).strip().lower()
        if conf not in {"high", "medium", "low"}:
            conf = "medium"
        return answer, prov_clean, conf
    except Exception as exc:
        log.warning("synth failed: %s", exc)
        # Fallback: stitch sub-query contexts together
        bits = []
        for sq in plan.sub_queries:
            if sq.result and sq.result.get("context"):
                bits.append(sq.result["context"][:600])
        return ("\n\n".join(bits) or "I'm unable to compose an answer.", {}, "low")


# ---- the public entry point -----------------------------------------------

async def execute_plan(
    user_query: str,
    *,
    history: list[dict] | None = None,
    top_k_per_subquery: int = 6,
) -> PlanResult:
    """Run the full plan-execute-reflect-synthesize pipeline.

    Returns a PlanResult containing the answer, citations, and full debug trace.
    Total cost: 2 + N + N (+optional retries) + 1 LLM calls.
    """
    # STEP 1: PLAN
    plan = await _plan(user_query, history)

    # STEP 2: EXECUTE all sub-queries in parallel
    await asyncio.gather(*(_execute_sub_query(sq, top_k=top_k_per_subquery)
                          for sq in plan.sub_queries))

    # STEP 3: REFLECT — judge each sub-query result in parallel
    await asyncio.gather(*(_reflect(sq) for sq in plan.sub_queries))

    # STEP 3b: RETRY low-quality sub-queries (capped at 1 retry each)
    retry_tasks = []
    for sq in plan.sub_queries:
        if sq.refined_query and sq.retry_count == 0:
            sq.retry_count = 1
            retry_tasks.append(_execute_sub_query(
                SubQuery(id=sq.id, query=sq.refined_query, intent=sq.intent,
                          expected=sq.expected, retry_count=1),
                top_k=top_k_per_subquery,
            ))
    if retry_tasks:
        # Note: retry results would normally replace the original; for simplicity
        # we run them and merge citations rather than fully replace. This keeps
        # the original signal in case the refinement was wrong.
        retry_results = await asyncio.gather(*retry_tasks, return_exceptions=True)
        for sq, retry_sq in zip(
            [s for s in plan.sub_queries if s.refined_query], retry_results,
        ):
            if isinstance(retry_sq, Exception):
                continue
            # Merge citations from original + retry (dedupe by act+section_number)
            orig_cites = (sq.result or {}).get("citations", [])
            retry_cites = (retry_sq.result if hasattr(retry_sq, "result") else {}).get("citations", []) if retry_sq else []
            seen = {(c.get("act"), c.get("section_number")) for c in orig_cites}
            for c in retry_cites:
                key = (c.get("act"), c.get("section_number"))
                if key not in seen:
                    orig_cites.append(c)
                    seen.add(key)

    # STEP 4: SYNTHESIZE
    answer, provenance, confidence = await _synthesize(plan)

    # Collect all citations across sub-queries, dedupe
    all_citations: list[dict[str, Any]] = []
    seen_cite: set[tuple[str, str]] = set()
    for sq in plan.sub_queries:
        for c in (sq.result or {}).get("citations", []):
            key = (c.get("act", ""), c.get("section_number", ""))
            if key not in seen_cite:
                seen_cite.add(key)
                all_citations.append(c)

    avg_quality = sum(sq.quality for sq in plan.sub_queries) / max(1, len(plan.sub_queries))
    n_citations = len(all_citations)

    # Confidence is computed deterministically from retrieval quality, not
    # from the synth LLM's self-assessment (it's reflexively conservative).
    if avg_quality >= 0.7 and n_citations >= 2:
        confidence = "high"
    elif avg_quality >= 0.5 and n_citations >= 1:
        confidence = "medium"
    else:
        confidence = "low"

    low_conf = avg_quality < 0.4 or n_citations == 0

    return PlanResult(
        plan=plan,
        answer=answer,
        citations=all_citations,
        provenance=provenance,
        confidence=confidence,
        low_confidence=low_conf,
        debug={
            "plan_id":       plan.plan_id,
            "intent":        plan.intent,
            "rewritten":     plan.rewritten_query,
            "sub_queries":   [
                {
                    "id": sq.id, "query": sq.query, "intent": sq.intent,
                    "quality": sq.quality, "missing": sq.missing,
                    "retry": sq.retry_count, "refined": sq.refined_query,
                    "n_citations": len((sq.result or {}).get("citations", [])),
                }
                for sq in plan.sub_queries
            ],
            "avg_quality":   avg_quality,
        },
    )


# Convenience: build a non-LLM-ranked fallback if everything fails
async def execute_plan_safe(user_query: str, **kwargs) -> PlanResult:
    try:
        return await execute_plan(user_query, **kwargs)
    except Exception as exc:
        log.exception("planner pipeline failed catastrophically: %s", exc)
        # Last-resort: single retrieve_context call
        result = await retrieve_context(user_query, top_k=kwargs.get("top_k_per_subquery", 6))
        fallback_plan = _fallback_plan(user_query)
        return PlanResult(
            plan=fallback_plan,
            answer="I'm having trouble processing your question. Please try rephrasing.",
            citations=result.get("citations", []),
            provenance={},
            confidence="low",
            low_confidence=True,
            debug={"error": str(exc), "fallback": True},
        )
