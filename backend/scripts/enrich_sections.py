"""Enrich parsed PDF sections with GPT-5-nano → richer Pinecone payload.

Why this exists:
  PyMuPDF gives us clean section text but synthesised/messy titles for ~20%
  of sections, and the embed text is just `title + raw body`. For queries
  like "punishment for theft" the relevant section's body uses statute-speak
  ("Whoever, intending to take dishonestly...") that doesn't semantically
  match the natural-language query. We need a layer that turns each section
  into a structured, query-friendly knowledge unit.

What it does:
  For each section produced by `parse_pdf()` in scripts/ingest_pdfs.py,
  call GPT-5-nano once to extract a compact JSON object:

    { title_clean, summary, key_terms, punishment, cross_references,
      hypothetical_questions, entities }

  Then write the whole corpus to data/sections_enriched.json. Idempotent —
  skips sections already in the output file (so re-runs only cost for new
  or `--force` sections).

Cost on full corpus (1044 sections, gpt-5-nano):
    ~$0.45 total, one-time. See README in scripts/ for the math.

Run inside backend container:
    docker compose exec backend python -m scripts.enrich_sections
    docker compose exec backend python -m scripts.enrich_sections --acts bns --force

Useful flags:
    --acts bns,bnss,bsa   subset (default: all three)
    --pdf-dir PATH        where PDFs live (default /app/data)
    --out PATH            output JSON (default /app/data/sections_enriched.json)
    --concurrency N       parallel LLM calls (default 8)
    --limit N             only enrich first N sections per act (debugging)
    --force               re-enrich sections already present in output
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
from scripts.ingest_pdfs import (  # noqa: E402
    ACTS, MARGIN_PCT_DEFAULT, SKIP_PAGES_DEFAULT,
    assemble_sections, find_section_starts, parse_pdf,
)

# ---------------------------------------------------------------------------
# Prompt — kept tight on purpose. Borrowed shape from LightRAG (compact JSON,
# entity list) but stripped down to what *legal* retrieval actually needs.
# ---------------------------------------------------------------------------

ENRICH_SYSTEM = """You are a legal-text normaliser for Indian criminal statutes
(BNS 2023, BNSS 2023, BSA 2023). Given the raw text of one section, return a
compact JSON object with the fields below. Be precise; don't invent facts not
present in the section text.

Return ONLY valid JSON in this exact shape:
{
  "title_clean":            "string  — the section's true short title (3-8 words). If the raw text already starts with `Title.—body`, use that title. If the section has no inherent title (procedural sections often don't), generate a concise descriptive title.",
  "summary":                "string  — 1-2 sentences explaining what the section does in plain English. State the offence/rule AND any punishment in the same sentence if applicable.",
  "key_terms":              ["string"]  — 3-7 short noun phrases a user might search by (e.g. ['theft', 'dishonest taking', 'movable property']). Lowercase.
  "punishment":             "string|null  — short phrase, e.g. 'imprisonment up to 3 years OR fine OR both'. null if section is not penal.",
  "cross_references":       [{"act":"BNS|BNSS|BSA","section":"N"}]  — sections explicitly named in the text. Empty array if none.
  "entities":               [{"type":"offence|defined_term|procedure","name":"string"}]  — 0-5 named entities. Only categorize as `offence` for substantive criminal acts, `defined_term` for words explicitly defined here, `procedure` for procedural rules.
  "hypothetical_questions": ["string"]  — exactly 5 distinct natural-language questions whose answer is THIS section. Vary phrasing (definitional, scenario-based, punishment-focused, etc.). Each ≤ 15 words.
}

Rules:
- No markdown, no commentary, no fences — JSON only.
- If the section is a definitions clause containing multiple terms, pick the most prominent one for entities and key_terms.
- For procedural sections (BNSS), the 'punishment' field is almost always null.
"""


def _build_user(*, act: str, number: str, raw_title: str, body: str) -> str:
    body_clip = body[:2400]
    return (
        f"ACT: {act}\n"
        f"SECTION NUMBER: {number}\n"
        f"RAW TITLE (may be messy): {raw_title}\n"
        f"SECTION TEXT:\n{body_clip}"
    )


# ---------------------------------------------------------------------------
# Per-section enrichment
# ---------------------------------------------------------------------------

async def enrich_one(llm, *, act: str, number: str, raw_title: str, body: str) -> dict:
    """One LLM call per section. Returns the enriched dict (with bookkeeping fields)."""
    user_msg = _build_user(act=act, number=number, raw_title=raw_title, body=body)
    data = await llm.complete_json(
        [
            {"role": "system", "content": ENRICH_SYSTEM},
            {"role": "user",   "content": user_msg},
        ],
        fast=True,
        max_tokens=900,
    )
    return {
        "act":                    act,
        "number":                 str(number),
        "raw_title":              raw_title,
        "raw_body":               body,
        "title_clean":            str(data.get("title_clean") or raw_title or f"Section {number}"),
        "summary":                str(data.get("summary") or ""),
        "key_terms":              [str(t).lower().strip() for t in (data.get("key_terms") or []) if t],
        "punishment":             data.get("punishment"),
        "cross_references":       [_norm_xref(x) for x in (data.get("cross_references") or []) if isinstance(x, dict)],
        "entities":               [_norm_entity(e) for e in (data.get("entities") or []) if isinstance(e, dict)],
        "hypothetical_questions": [str(q).strip() for q in (data.get("hypothetical_questions") or []) if q][:5],
    }


def _norm_xref(x: dict) -> dict:
    return {
        "act":     str(x.get("act") or "").upper(),
        "section": str(x.get("section") or "").strip(),
    }


def _norm_entity(e: dict) -> dict:
    t = str(e.get("type") or "").lower().strip()
    if t not in {"offence", "defined_term", "procedure"}:
        t = "defined_term"
    return {"type": t, "name": str(e.get("name") or "").strip()}


# ---------------------------------------------------------------------------
# Main: parse PDFs → enrich missing sections → write JSON
# ---------------------------------------------------------------------------

async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--acts",        default="bns,bnss,bsa")
    parser.add_argument("--pdf-dir",     default="/app/data")
    parser.add_argument("--out",         default="/app/data/sections_enriched.json")
    parser.add_argument("--skip-pages",  type=int,   default=SKIP_PAGES_DEFAULT)
    parser.add_argument("--margin-pct",  type=float, default=MARGIN_PCT_DEFAULT)
    parser.add_argument("--concurrency", type=int,   default=8)
    parser.add_argument("--limit",       type=int,   default=0,
                        help="enrich only the first N sections per act (debugging)")
    parser.add_argument("--force",       action="store_true",
                        help="re-enrich even sections already in the output file")
    args = parser.parse_args()

    pdf_dir = Path(args.pdf_dir)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    chosen = [a.strip().lower() for a in args.acts.split(",") if a.strip()]
    for a in chosen:
        if a not in ACTS:
            raise SystemExit(f"unknown act '{a}'. choices: {','.join(ACTS)}")

    # Load existing enriched records so we can skip them.
    existing: dict[str, dict] = {}
    if out_path.exists() and not args.force:
        try:
            existing = {f"{r['act']}_{r['number']}": r
                        for r in json.loads(out_path.read_text())}
            print(f"Loaded {len(existing)} previously enriched sections "
                  f"(use --force to redo)", flush=True)
        except Exception as exc:
            print(f"⚠  could not read {out_path} ({exc}); starting fresh")
            existing = {}

    # ----- Step 1: parse each PDF (PyMuPDF column-aware) -----
    todo: list[tuple[str, str, str, str]] = []   # (act, number, title, body)
    for a in chosen:
        meta = ACTS[a]
        path = pdf_dir / meta["file"]
        if not path.exists():
            print(f"⚠  {meta['name']} skipped — {path} not found")
            continue
        parsed = parse_pdf(path, skip_pages=args.skip_pages, margin_pct=args.margin_pct)
        starts = find_section_starts(parsed.body_lines, max_section=meta["max_section"])
        sections = assemble_sections(
            parsed.body_lines, starts, parsed.marginalia,
            act_name=meta["name"], category=meta["category"],
        )
        if args.limit:
            sections = sections[: args.limit]
        for s in sections:
            todo.append((s.act, s.number, s.title, s.text))
        print(f"→ {meta['name']:5s}  parsed {len(sections)} sections", flush=True)

    # ----- Step 2: filter out already-enriched -----
    to_enrich = [t for t in todo if f"{t[0]}_{t[1]}" not in existing]
    print(f"\nEnriching {len(to_enrich)} sections "
          f"({len(todo) - len(to_enrich)} cached) "
          f"with concurrency={args.concurrency}\n", flush=True)

    if not to_enrich:
        print("Nothing to do.")
        return

    # ----- Step 3: parallel LLM calls -----
    llm = get_llm()
    sem = asyncio.Semaphore(args.concurrency)
    results: dict[str, dict] = dict(existing)
    failed: list[tuple[str, str, str]] = []
    completed = 0
    t0 = time.perf_counter()

    async def worker(act: str, num: str, title: str, body: str) -> None:
        nonlocal completed
        async with sem:
            try:
                enriched = await enrich_one(llm, act=act, number=num,
                                            raw_title=title, body=body)
                results[f"{act}_{num}"] = enriched
            except Exception as exc:
                failed.append((act, num, str(exc)[:120]))
            completed += 1
            if completed % 20 == 0 or completed == len(to_enrich):
                elapsed = time.perf_counter() - t0
                rate = completed / max(elapsed, 0.1)
                eta = (len(to_enrich) - completed) / max(rate, 0.1)
                print(f"   {completed}/{len(to_enrich)}  "
                      f"({rate:.1f}/s, eta {eta:.0f}s, failed={len(failed)})",
                      flush=True)

    await asyncio.gather(*(worker(a, n, t, b) for a, n, t, b in to_enrich))

    # ----- Step 4: persist (sort for deterministic diff) -----
    records = sorted(results.values(), key=lambda r: (r["act"], int(r["number"])))
    out_path.write_text(json.dumps(records, indent=2, ensure_ascii=False))
    print(f"\n✓ wrote {len(records)} sections → {out_path}")

    if failed:
        print(f"\n⚠  {len(failed)} sections failed (re-run to retry):")
        for a, n, e in failed[:10]:
            print(f"   {a} {n}: {e}")
        if len(failed) > 10:
            print(f"   …and {len(failed) - 10} more")


if __name__ == "__main__":
    asyncio.run(main())
