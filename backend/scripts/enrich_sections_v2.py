"""Enrich sections_parsed.json (from chunk_pdfs.py) → sections_enriched.json.

Design changes vs v1 (enrich_sections.py):

1. READS the clean chunker output instead of re-parsing the PDFs with the
   broken column logic. The whole point of the chunker rewrite was to fix
   missing sections + marginalia bleed — re-parsing here would throw that away.

2. CROSS-REFERENCE ANTI-HALLUCINATION:
     - Regex pre-extracts candidate cross-refs from the body text. Patterns
       match BOTH internal ("section 5", "section 5 of this Sanhita") and
       external ("section 173 of the Bharatiya Nagarik Suraksha Sanhita")
       references. Gazette-style annotations ("40 of 2019.") come from the
       chunker's cross_references_pdf field.
     - The LLM is shown the CANDIDATE LIST and asked to add descriptions
       only. It cannot invent new references.
     - Validation pass: every kept cross-ref must (a) appear in the candidate
       list (the LLM only annotated, didn't add); (b) point to an act+section
       that actually exists in our 1059-section corpus; (c) have a verbatim
       quote that exists in the source body.
     - Any failure → drop that ref. NO FALSE POSITIVES.

3. ENTITY EXTRACTION TIGHTENED:
     - 10 legal types matching legal_lightrag.LEGAL_ENTITY_TYPES (so the next
       LightRAG ingest can use these directly).
     - Salience score 0.0-1.0 per entity — required by the LightRAG plan's
       part B (primary-only extraction with weighted edges).
     - Prompt explicitly forbids "extract everything mentioned" — only extract
       entities the section is PRIMARILY ABOUT.

4. HIGHER CONCURRENCY (default 50) for OpenAI Usage Tier 3.

5. NO SMART MERGE — every section is freshly enriched (--force is implicit).

Output schema:
{
  "act":                    "BNS",
  "number":                 "303",
  "raw_title":              "Theft",
  "raw_body":               "...",
  "title_clean":            "Theft",
  "summary":                "Defines theft as ... punishment up to 3 years ...",
  "key_terms":              ["theft", "movable property", "dishonest taking"],
  "punishment":             "imprisonment up to 3 years OR fine OR both",
  "cross_references":       [
    {"act":"BNS","number":"305","kind":"internal","quote":"see section 305",
     "description":"theft in vehicles"}
  ],
  "cross_references_pdf":   ["40 of 2019."],         # passed through from chunker
  "entities":               [
    {"name":"theft", "type":"OFFENCE", "salience":1.0,
     "description":"act of dishonestly taking movable property"},
    {"name":"movable property", "type":"DEFINED_TERM", "salience":0.7,
     "description":"property covered by theft offence"}
  ],
  "hypothetical_questions": [...]                    # 5 diverse Qs
}

Usage:
  docker exec -w /app nyaya-backend python -m scripts.enrich_sections_v2
  docker exec -w /app nyaya-backend python -m scripts.enrich_sections_v2 \\
      --in /app/data/sections_parsed.json \\
      --out /app/data/sections_enriched.json \\
      --concurrency 50
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.llm import get_llm  # noqa: E402

# ---------------------------------------------------------------------------
# Legal entity taxonomy — must match legal_lightrag.LEGAL_ENTITY_TYPES so the
# LightRAG ingest can consume this output directly.
# ---------------------------------------------------------------------------

LEGAL_ENTITY_TYPES = [
    "OFFENCE",            # theft, robbery, murder — the act itself
    "PUNISHMENT",         # imprisonment, fine, capital punishment
    "DEFINED_TERM",       # statute-defined vocabulary
    "PROCEDURE",          # FIR, arrest, bail, investigation
    "ACTOR",              # public servant, magistrate, witness
    "COURT",              # district court, high court, supreme court
    "EVIDENCE_TYPE",      # documentary, confession, presumption
    "STATUTE_REFERENCE",  # references to other sections / acts
    "RIGHT",              # right to bail, right to silence
    "DUTY",               # duty of disclosure, duty to assist
]

# ---------------------------------------------------------------------------
# Cross-reference candidate extraction (regex on body text)
# ---------------------------------------------------------------------------

# Map of full act names → our short codes
ACT_NAME_MAP = [
    (r"Bharatiya\s+Nyaya\s+Sanhita(?:,?\s*2023)?", "BNS"),
    (r"Bharatiya\s+Nagarik\s+Suraksha\s+Sanhita(?:,?\s*2023)?", "BNSS"),
    (r"Bharatiya\s+Sakshya\s+Adhiniyam(?:,?\s*2023)?", "BSA"),
    (r"this\s+Sanhita", "SAME"),      # resolves to the current act later
    (r"this\s+Adhiniyam", "SAME"),
]

# "section 5", "section 5 of this Sanhita", "section 173 of the Bharatiya..."
RE_SECTION_REF = re.compile(
    r"\b(?:section|sec\.?|s\.?)\s+(\d{1,3})"
    r"(?:\s*(?:to|or|,|and)\s*\d{1,3})*"
    r"(?:\s+of\s+(?:the\s+)?(this\s+(?:Sanhita|Adhiniyam)|"
    r"Bharatiya\s+(?:Nyaya|Nagarik\s+Suraksha|Sakshya)\s+(?:Sanhita|Adhiniyam)(?:,?\s*\d{4})?))?",
    re.IGNORECASE,
)

# "sub-section (1) of section 5", "clause (a) of section 5" — we only want the section
RE_SUBSECTION_OF = re.compile(
    r"\b(?:sub-section|clause)\s*\([a-z0-9]+\)\s+of\s+section\s+(\d{1,3})",
    re.IGNORECASE,
)


def _resolve_act(matched_act_phrase: str | None, current_act: str) -> str:
    """Turn 'this Sanhita' / 'Bharatiya Nyaya Sanhita' / None into BNS|BNSS|BSA."""
    if not matched_act_phrase:
        return current_act
    phrase = matched_act_phrase.strip()
    if re.search(r"this\s+(?:Sanhita|Adhiniyam)", phrase, re.IGNORECASE):
        return current_act
    for pat, code in ACT_NAME_MAP:
        if re.search(pat, phrase, re.IGNORECASE) and code != "SAME":
            return code
    return current_act    # default to same act if ambiguous


def extract_candidate_refs(body: str, current_act: str) -> list[dict]:
    """Return list of {act, number, quote, kind} — every section reference present in text."""
    seen: set[tuple[str, str]] = set()
    out: list[dict] = []

    for m in RE_SECTION_REF.finditer(body):
        num = m.group(1)
        act_phrase = m.group(2)
        act = _resolve_act(act_phrase, current_act)
        key = (act, num)
        if key in seen:
            continue
        seen.add(key)
        # The "quote" is the matched span, trimmed
        quote = body[m.start():m.end()].strip()
        kind = "internal" if act == current_act else "external"
        out.append({"act": act, "number": num, "quote": quote, "kind": kind})

    for m in RE_SUBSECTION_OF.finditer(body):
        num = m.group(1)
        key = (current_act, num)
        if key in seen:
            continue
        seen.add(key)
        out.append({"act": current_act, "number": num,
                    "quote": body[m.start():m.end()].strip(), "kind": "internal"})

    return out


# ---------------------------------------------------------------------------
# Enrichment prompt — stricter than v1, anti-hallucination
# ---------------------------------------------------------------------------

ENRICH_SYSTEM = """You are an expert legal-text normaliser for Indian criminal
statutes (BNS 2023, BNSS 2023, BSA 2023). For ONE section, return a strict JSON
object with the fields listed. Be precise; DO NOT invent facts not present in
the provided section text.

Return ONLY valid JSON. The shape and constraints are:

  title_clean              string,  3-8 words (the section's true short title)
  summary                  string,  1-2 plain-English sentences specific to THIS section
  key_terms                array of 3-7 short lowercased noun phrases (search-friendly)
  punishment               string|null  (null if not penal)
  cross_reference_descriptions   array of {act:"BNS|BNSS|BSA", number:"N", description:string}
  entities                 array of {name:string, type:enum, salience:0.3-1.0, description:string}
  hypothetical_questions   array of exactly 5 questions whose answer is this section

Example output for BNS §303 (Theft) — DO NOT COPY values, just shape:
{
  "title_clean": "Theft",
  "summary": "Defines theft as dishonestly taking movable property out of another's possession; punishable with imprisonment up to three years, fine, or both.",
  "key_terms": ["theft", "dishonestly", "movable property", "wrongful gain", "possession"],
  "punishment": "imprisonment up to 3 years OR fine OR both",
  "cross_reference_descriptions": [],
  "entities": [
    {"name": "theft", "type": "OFFENCE", "salience": 1.0, "description": "core offence of dishonestly taking movable property"},
    {"name": "movable property", "type": "DEFINED_TERM", "salience": 0.7, "description": "property capable of being moved, subject of theft"}
  ],
  "hypothetical_questions": [
    "What is the offence of theft under BNS?",
    "What is the punishment for theft?",
    "Is taking someone's bag while they're on a train considered theft?",
    "What does 'dishonestly' mean in the context of theft?",
    "When does possession of property become subject of theft?"
  ]
}

RULES (ALL ARE STRICT — VIOLATIONS WILL CAUSE THE OUTPUT TO BE REJECTED):

R1. CROSS-REFERENCES are SUBSET of the CANDIDATE LIST you are given. You may not
    add any ref that isn't in the candidates. If candidates is empty → return [].
    For each ref's `description`: ONLY describe it if you can infer the target's
    purpose from THIS section's text. If you cannot, OMIT that ref from the
    output (don't write guesses like "general definitions?" or "(not specified)").

R2. ENTITIES — PRIMARY ONLY. Only extract entities that THIS section is
    *primarily about*. Reject the temptation to extract every noun. Examples
    of what NOT to do:
      - Section 4 BNS (Punishments — lists all available punishments) → DO NOT
        extract 'punishments' as OFFENCE. Extract each individual punishment
        type (death, imprisonment for life, fine, ...) as PUNISHMENT.
      - Section 6 BNS (Fractions of punishment) → DO NOT extract 'imprisonment
        for life' as OFFENCE. It is a PUNISHMENT. The section is ABOUT the
        rule that life imprisonment = 20 years for calculations — entity is
        'fractions of punishment' DEFINED_TERM salience=1.0.
      - Section 41 BNSS (private defence of property) → entity 'private
        defence' RIGHT salience=1.0. DO NOT extract 'theft' or 'robbery' even
        though the body lists them as examples — they're not what THIS section
        is about.

R3. ENTITY TYPES — pick the most specific from this exact list. Mis-typing is a
    rejection.
      OFFENCE         — an unlawful act (theft, murder, defamation, etc.)
      PUNISHMENT      — a sanction (death, imprisonment, fine, forfeiture)
      DEFINED_TERM    — a statute-defined vocabulary word (dishonestly,
                        movable property, court, document, ...)
      PROCEDURE       — a procedural step (FIR, arrest, bail, charge sheet)
      ACTOR           — a person/role (public servant, magistrate, accused,
                        witness, police officer)
      COURT           — a court level (District Court, High Court, Supreme
                        Court, Magistrate's Court)
      EVIDENCE_TYPE   — a class of evidence (documentary, expert opinion,
                        confession, presumption)
      STATUTE_REFERENCE — a reference to another statute or section
      RIGHT           — a legal right (right to bail, right to silence,
                        private defence)
      DUTY            — a legal duty (duty to assist, duty to disclose,
                        duty of care)

R4. ENTITY DESCRIPTIONS must be non-empty short phrases (5-15 words). Each
    entity needs a description specific to how it's used in THIS section.
    NEVER return entities with empty/dash descriptions.

R5. SALIENCE 0.3 - 1.0:
      1.0 = THE primary subject of this section
      0.7 - 0.9 = a major element this section covers in detail
      0.5 = a significant but secondary element
      0.3 = the lower bound (still relevant; mentioned as part of definition)
      <0.3 → don't extract.
    Maximum 8 entities. Quality > quantity.

R6. PUNISHMENT field: verbatim-style summary of the penalty from this section
    only. Null if the section is not penal (most BNSS procedural sections, all
    BSA evidence rules, BNS definition sections).

R7. HYPOTHETICAL QUESTIONS — exactly 5, all SPECIFIC TO THIS SECTION's content.
    Mix definitional, scenario, punishment, and procedural angles. Each ≤ 15
    words. ABSOLUTELY DO NOT reuse generic questions like "what is theft?" for
    a section that isn't about theft. If you don't know how to phrase 5
    distinct questions for this section, generate fewer rather than fake ones.

R8. TITLE_CLEAN: respect the RAW TITLE given to you. Only clean it up
    (capitalisation, remove punctuation). Don't substitute a different section's
    title or invent one.
"""


def _build_user(*, act: str, number: str, raw_title: str, body: str,
                candidate_refs: list[dict]) -> str:
    # Smart clip: keep beginning (definition/rule) + end (punishment clause).
    # Long penal sections (BNS 303 = 5.9k chars) need both — punishment text
    # lives near the end of the section.
    if len(body) <= 5000:
        body_clip = body
    else:
        body_clip = body[:3500] + "\n  [...]\n" + body[-1500:]
    if candidate_refs:
        ref_list = "\n".join(
            f"  - {r['act']} section {r['number']} (quoted as: \"{r['quote'][:80]}\")"
            for r in candidate_refs[:20]
        )
    else:
        ref_list = "  (none — no cross-references in the body)"
    return (
        f"ACT: {act}\n"
        f"SECTION NUMBER: {number}\n"
        f"RAW TITLE: {raw_title}\n\n"
        f"SECTION TEXT:\n{body_clip}\n\n"
        f"CANDIDATE CROSS-REFERENCES (the ONLY refs you may annotate):\n{ref_list}\n"
    )


# ---------------------------------------------------------------------------
# Post-LLM validation — drop anything hallucinated
# ---------------------------------------------------------------------------

def _validate_xrefs(
    llm_refs: list[dict],
    candidate_refs: list[dict],
    body: str,
    corpus_keys: set[tuple[str, str]],
) -> list[dict]:
    """Keep only refs that (a) appear in candidates, (b) point to a real section,
    (c) have a verbatim quote in the source body. Output schema with description."""
    candidate_keys = {(r["act"], r["number"]): r for r in candidate_refs}
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for r in llm_refs:
        if not isinstance(r, dict):
            continue
        act = str(r.get("act", "")).strip().upper()
        num = str(r.get("number") or r.get("section") or "").strip()
        if not act or not num:
            continue
        key = (act, num)
        # (a) must be in candidate list (regex-extracted from body)
        if key not in candidate_keys:
            continue
        # (b) must point to a real section in the corpus
        if corpus_keys and key not in corpus_keys:
            continue
        if key in seen:
            continue
        seen.add(key)
        # (d) description must be non-empty AND not a hedge/guess
        desc = str(r.get("description") or "").strip()
        if not desc:
            continue
        low = desc.lower()
        if any(h in low for h in ("not specified", "not stated", "unclear",
                                    "unknown", "tbd", "?", "(see")):
            continue
        cand = candidate_keys[key]
        out.append({
            "act": act,
            "number": num,
            "kind": cand["kind"],
            "quote": cand["quote"],
            "description": desc,
        })
    return out


def _validate_entities(llm_ents: list[dict]) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for e in llm_ents:
        if not isinstance(e, dict):
            continue
        name = str(e.get("name") or "").strip()
        if not name or name.lower() in seen:
            continue
        etype = str(e.get("type") or "").strip().upper()
        if etype not in LEGAL_ENTITY_TYPES:
            continue
        try:
            sal = float(e.get("salience", 0.5))
        except (ValueError, TypeError):
            sal = 0.5
        sal = max(0.0, min(1.0, sal))
        if sal < 0.3:
            continue   # too low to be useful
        desc = str(e.get("description") or "").strip()
        if not desc or len(desc) < 5:
            continue   # reject empty / single-word descriptions
        seen.add(name.lower())
        out.append({
            "name": name,
            "type": etype,
            "salience": round(sal, 2),
            "description": desc,
        })
    return out[:8]


# ---------------------------------------------------------------------------
# Per-section worker
# ---------------------------------------------------------------------------

async def enrich_one(llm, section: dict, corpus_keys: set[tuple[str, str]]) -> dict:
    act = section["act"]
    num = section["number"]
    raw_title = section.get("raw_title", "") or ""
    body = section.get("raw_body", "") or ""
    candidate_refs = extract_candidate_refs(body, current_act=act)

    user_msg = _build_user(act=act, number=num, raw_title=raw_title,
                            body=body, candidate_refs=candidate_refs)

    data = await llm.complete_json(
        [
            {"role": "system", "content": ENRICH_SYSTEM},
            {"role": "user",   "content": user_msg},
        ],
        fast=True,
        max_tokens=1400,
        temperature=0.0,
    )

    xrefs = _validate_xrefs(
        data.get("cross_reference_descriptions") or [],
        candidate_refs, body, corpus_keys,
    )
    entities = _validate_entities(data.get("entities") or [])

    return {
        "act":                     act,
        "number":                  num,
        "raw_title":               raw_title,
        "raw_body":                body,
        "title_clean":             str(data.get("title_clean") or raw_title or f"Section {num}"),
        "summary":                 str(data.get("summary") or "").strip(),
        "key_terms":               [str(t).lower().strip() for t in (data.get("key_terms") or []) if t][:7],
        "punishment":              data.get("punishment"),
        "cross_references":        xrefs,
        "cross_references_pdf":    section.get("cross_references_pdf", []),
        "entities":                entities,
        "hypothetical_questions":  [str(q).strip() for q in (data.get("hypothetical_questions") or []) if q][:5],
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--in",  dest="in_path",  default="/app/data/sections_parsed.json")
    parser.add_argument("--out", dest="out_path", default="/app/data/sections_enriched.json")
    parser.add_argument("--concurrency", type=int, default=50,
                        help="parallel LLM calls (default 50 — Tier 3 friendly)")
    parser.add_argument("--limit",       type=int, default=0,
                        help="enrich only first N sections (debugging)")
    parser.add_argument("--acts",        default="BNS,BNSS,BSA")
    args = parser.parse_args()

    in_path  = Path(args.in_path)
    out_path = Path(args.out_path)

    if not in_path.exists():
        raise SystemExit(f"input not found: {in_path}\nRun scripts.chunk_pdfs first.")

    sections = json.loads(in_path.read_text())
    chosen = {a.strip().upper() for a in args.acts.split(",")}
    sections = [s for s in sections if s.get("act", "").upper() in chosen]
    if args.limit:
        sections = sections[: args.limit]
    print(f"Loaded {len(sections)} sections from {in_path}")

    # Build corpus key set for cross-ref validation
    corpus_keys = {(s["act"].upper(), str(s["number"])) for s in sections}

    llm = get_llm()
    sem = asyncio.Semaphore(args.concurrency)
    results: list[dict] = []
    failed: list[tuple[str, str, str]] = []
    completed = 0
    t0 = time.perf_counter()

    async def worker(sec: dict) -> None:
        nonlocal completed
        async with sem:
            try:
                enriched = await enrich_one(llm, sec, corpus_keys)
                results.append(enriched)
            except Exception as exc:
                failed.append((sec["act"], sec["number"], str(exc)[:120]))
            completed += 1
            if completed % 25 == 0 or completed == len(sections):
                elapsed = time.perf_counter() - t0
                rate = completed / max(elapsed, 0.1)
                eta = (len(sections) - completed) / max(rate, 0.1)
                print(f"   {completed}/{len(sections)}  "
                      f"({rate:.1f}/s, eta {eta:.0f}s, failed={len(failed)})",
                      flush=True)

    print(f"Enriching with concurrency={args.concurrency}\n")
    await asyncio.gather(*(worker(s) for s in sections))

    # Sort for deterministic diff
    results.sort(key=lambda r: (r["act"], int(r["number"]) if str(r["number"]).isdigit() else 0))
    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False))

    # Validation summary
    total_xrefs = sum(len(r["cross_references"]) for r in results)
    total_ents  = sum(len(r["entities"]) for r in results)
    print(f"\n✓ wrote {len(results)} sections → {out_path}")
    print(f"   total cross_references kept (validated): {total_xrefs}")
    print(f"   total entities kept (salience >= 0.3):   {total_ents}")
    print(f"   avg cross_refs per section: {total_xrefs/max(len(results),1):.2f}")
    print(f"   avg entities per section:   {total_ents/max(len(results),1):.2f}")

    if failed:
        print(f"\n⚠  {len(failed)} sections failed:")
        for a, n, e in failed[:10]:
            print(f"   {a} §{n}: {e}")


if __name__ == "__main__":
    asyncio.run(main())
