"""LLM-only PDF parser: GPT-5-nano reads each PDF chunk → structured sections.

Why this exists:
  PyMuPDF + regex parser is at 98.5% (missing ~16 sections, occasional title
  glitches) and requires per-PDF tuning (margin-pct, skip-pages, regex tweaks).
  This pipeline asks GPT-5-nano to do the structuring directly from cleaned
  page text — no marginalia logic, no column detection, no monotonic-sequence
  filter. The LLM reads the act like a human and emits structured sections.

Output is the SAME shape as scripts/enrich_sections.py:
    data/sections_enriched.json — array of {act, number, title_clean, summary,
                                            key_terms, punishment,
                                            cross_references, entities,
                                            hypothetical_questions, raw_body}

So scripts/ingest_pdfs.py --enriched <path> works against either parser.

Pipeline:
  1. PyMuPDF: extract whole-page text (plain — no column logic).
  2. Strip running headers / page numbers / running title.
  3. Batch pages: 4-page chunks with 1-page overlap (sections spanning chunk
     boundaries get fully captured in at least one chunk).
  4. Parallel GPT-5-nano calls — one per chunk → JSON sections array.
  5. Stitch: dedupe by (act, number), keep the version with the longest body.

Cost on full corpus (1044 sections / ~720 pages):
    ~240 LLM calls × ~$0.0015 = ~$0.40 one-time.

Run inside backend container:
    docker compose exec backend python -m scripts.parse_pdfs_llm
    docker compose exec backend python -m scripts.parse_pdfs_llm --acts bns --limit-pages 20

Useful flags:
    --acts bns,bnss,bsa     subset (default: all three)
    --pdf-dir PATH          where PDFs live (default /app/data)
    --out PATH              output JSON (default /app/data/sections_llm.json)
    --pages-per-chunk N     pages per LLM call (default 4)
    --overlap N             pages of overlap between chunks (default 1)
    --skip-pages N          skip first N pages of each PDF (default 2)
    --concurrency N         parallel LLM calls (default 8)
    --limit-pages N         debug: only parse first N pages of each PDF
    --force                 re-parse even if --out file already exists
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

import pymupdf  # noqa: E402

from app.core.llm import get_llm  # noqa: E402

# ---------------------------------------------------------------------------
# Act metadata (same as ingest_pdfs.py — kept independent so this script
# doesn't depend on the old PyMuPDF parser at all)
# ---------------------------------------------------------------------------

ACTS = {
    "bns":  {"file": "bns.pdf",  "name": "BNS",  "max_section": 360},
    "bnss": {"file": "bnss.pdf", "name": "BNSS", "max_section": 540},
    "bsa":  {"file": "bsa.pdf",  "name": "BSA",  "max_section": 175},
}

# ---------------------------------------------------------------------------
# Cleaning — strip the things that confuse the model without losing context
# ---------------------------------------------------------------------------

_NOISE_PATTERNS = [
    re.compile(r"(?m)^\s*\d{1,4}\s*$"),                   # bare page numbers
    re.compile(r"(?i)^\s*THE\s+GAZETTE\s+OF\s+INDIA.*$", re.M),
    re.compile(r"(?i)^\s*\[?\s*Part\s+[IVX]+.*$",         re.M),
    re.compile(r"(?i)^\s*Sec\.?\s*\d+\s*\].*$",           re.M),
    re.compile(r"(?i)^\s*THE\s+BHARATIYA[^\n]+(SANHITA|ADHINIYAM)[^\n]*$", re.M),
]


def clean_page(text: str) -> str:
    for pat in _NOISE_PATTERNS:
        text = pat.sub("", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_pages(pdf_path: Path, *, skip_pages: int) -> list[str]:
    """Return list of cleaned per-page text strings (no column logic)."""
    pages: list[str] = []
    with pymupdf.open(pdf_path) as doc:
        for i in range(skip_pages, doc.page_count):
            raw = doc[i].get_text() or ""
            pages.append(clean_page(raw))
    return pages


# ---------------------------------------------------------------------------
# Prompt — asks GPT-5-nano to find every section in the chunk and emit the
# same shape sections_enriched.json uses. Borrowed phrasing from LightRAG's
# extraction prompt (compact JSON, no fences, no commentary).
# ---------------------------------------------------------------------------

PARSE_SYSTEM = """You are a legal-text parser for Indian criminal statutes:
- BNS  = Bharatiya Nyaya Sanhita, 2023 (substantive criminal offences, sections 1-358)
- BNSS = Bharatiya Nagarik Suraksha Sanhita, 2023 (criminal procedure, sections 1-531)
- BSA  = Bharatiya Sakshya Adhiniyam, 2023 (evidence law, sections 1-170)

You receive a chunk of page text from ONE act. Find EVERY section in the chunk
and return a structured JSON object.

Section markers look like:
  "4. The punishments to which offenders..."
  "100. Culpable homicide.—Whoever causes..."
  "303. Theft.—Whoever, intending to..."

The TITLE — handle these three cases:
  (a) Inline `Title.—body`: cut at `.—`, `:—`, `.--`, or ` — `.
        e.g. "303. Theft.—Whoever..." → title = "Theft"
  (b) Left-margin marginalia words before the section number:
        e.g. "Punishments. 4. The punishments..." → title = "Punishments"
  (c) No title at all (body starts immediately after N.):
        GENERATE a 2-6 word descriptive title summarising the section.
        DO NOT use the body text verbatim as the title.
        e.g. "6. In calculating fractions of terms of punishment..." → title = "Fractions of terms of punishment"

EVERY section number that appears in the text MUST be in the output. If you see
"9." followed by body and later "11." followed by body, "10." MUST also be in
the output if it appears in between — don't skip sections.

Skip chapter headers ("CHAPTER II", "OF PUNISHMENTS"), tables of contents
(lines with dotted leaders or `... 142`), schedule entries, and page artifacts.

Return ONLY valid JSON in this exact shape:
{
  "sections": [
    {
      "number":           "303",
      "title":            "Theft",
      "body":             "Whoever, intending to take dishonestly any movable property...",
      "summary":          "1-2 sentence plain-English explanation INCLUDING punishment.",
      "key_terms":        ["theft", "dishonestly", "movable property"],
      "punishment":       "imprisonment up to 3 years OR fine OR both",
      "cross_references": [{"act":"BNS","section":"304"}],
      "entities":         [{"type":"offence","name":"theft"}],
      "hypothetical_questions": [
        "What is the punishment for theft?",
        "Define theft under BNS",
        "Someone stole my laptop — what section applies?",
        "Is dishonest taking without consent theft?",
        "What is the difference between theft and robbery?"
      ],
      "continues": false
    }
  ]
}

Rules:
- Set continues=true if the section's text appears to extend past the chunk end
  (i.e. you don't see the next section's number after this one's body).
- Don't fabricate sections — only return what's actually in the text.
- Don't return chapter headers, ToC entries, page numbers, or schedules as sections.
- punishment: null for procedural/definitional sections.
- entities[].type ∈ {"offence", "defined_term", "procedure"}.
- Exactly 5 hypothetical_questions per section, varied phrasing, each ≤ 15 words.
- body: clean prose, no page numbers or marginalia mixed in.
- No markdown, no commentary, no fences. JSON only.
"""


def _build_user(*, act_name: str, page_start: int, page_end: int, text: str) -> str:
    return (
        f"ACT: {act_name}\n"
        f"PAGES: {page_start}–{page_end}\n\n"
        f"TEXT:\n{text}"
    )


# ---------------------------------------------------------------------------
# Chunking + LLM call
# ---------------------------------------------------------------------------

def chunk_pages(pages: list[str], *, pages_per_chunk: int, overlap: int) -> list[tuple[int, int, str]]:
    """Yield (page_start, page_end, joined_text). 1-indexed page numbers.

    Overlap means consecutive chunks share `overlap` trailing pages — a section
    that spans the boundary appears fully in at least one chunk.
    """
    chunks: list[tuple[int, int, str]] = []
    step = max(1, pages_per_chunk - overlap)
    n = len(pages)
    i = 0
    while i < n:
        end = min(i + pages_per_chunk, n)
        text = "\n\n".join(pages[i:end]).strip()
        if text:
            chunks.append((i + 1, end, text))
        if end >= n:
            break
        i += step
    return chunks


async def parse_chunk(llm, *, act_name: str, page_start: int, page_end: int, text: str) -> list[dict]:
    """One LLM call → list of section dicts (may be empty)."""
    user_msg = _build_user(act_name=act_name, page_start=page_start, page_end=page_end, text=text)
    try:
        data = await llm.complete_json(
            [
                {"role": "system", "content": PARSE_SYSTEM},
                {"role": "user",   "content": user_msg},
            ],
            fast=True,
            max_tokens=6000,
        )
    except Exception:
        return []
    raw_sections = data.get("sections") or []
    if not isinstance(raw_sections, list):
        return []
    return [_normalise(s, act_name) for s in raw_sections if isinstance(s, dict)]


def _normalise(s: dict, act_name: str) -> dict:
    num = str(s.get("number") or "").strip()
    return {
        "act":              act_name,
        "number":           num,
        "title_clean":      str(s.get("title") or "").strip() or f"Section {num}",
        "raw_title":        str(s.get("title") or "").strip(),
        "raw_body":         str(s.get("body") or "").strip(),
        "summary":          str(s.get("summary") or "").strip(),
        "key_terms":        [str(t).lower().strip() for t in (s.get("key_terms") or []) if t],
        "punishment":       s.get("punishment"),
        "cross_references": [{"act": str(x.get("act","")).upper(),
                              "section": str(x.get("section","")).strip()}
                             for x in (s.get("cross_references") or []) if isinstance(x, dict)],
        "entities":         [{"type": str(e.get("type","")).lower(),
                              "name": str(e.get("name","")).strip()}
                             for e in (s.get("entities") or []) if isinstance(e, dict)],
        "hypothetical_questions": [str(q).strip() for q in (s.get("hypothetical_questions") or []) if q][:5],
        "continues":        bool(s.get("continues")),
    }


# ---------------------------------------------------------------------------
# Stitch — dedupe across chunks, keep longest body per (act, number)
# ---------------------------------------------------------------------------

def stitch(sections: list[dict], *, max_section: int) -> list[dict]:
    by_key: dict[tuple[str, str], dict] = {}
    for s in sections:
        num = s["number"]
        if not num or not num.isdigit():
            continue
        n = int(num)
        if not (1 <= n <= max_section):
            continue
        key = (s["act"], num)
        existing = by_key.get(key)
        if existing is None or len(s["raw_body"]) > len(existing["raw_body"]):
            by_key[key] = {**s, "continues": False}  # always reset continues after stitch
    return sorted(by_key.values(), key=lambda r: int(r["number"]))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--acts",            default="bns,bnss,bsa")
    p.add_argument("--pdf-dir",         default="/app/data")
    p.add_argument("--out",             default="/app/data/sections_llm.json")
    p.add_argument("--pages-per-chunk", type=int, default=4)
    p.add_argument("--overlap",         type=int, default=1)
    p.add_argument("--skip-pages",      type=int, default=2)
    p.add_argument("--concurrency",     type=int, default=8)
    p.add_argument("--limit-pages",     type=int, default=0)
    p.add_argument("--force",           action="store_true")
    args = p.parse_args()

    pdf_dir = Path(args.pdf_dir)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if out_path.exists() and not args.force:
        print(f"{out_path} already exists — pass --force to overwrite.")
        return

    chosen = [a.strip().lower() for a in args.acts.split(",") if a.strip()]
    for a in chosen:
        if a not in ACTS:
            raise SystemExit(f"unknown act '{a}'. choices: {','.join(ACTS)}")

    print(f"LLM-parsing PDFs in {pdf_dir} → {out_path}", flush=True)
    print(f"   pages-per-chunk={args.pages_per_chunk} overlap={args.overlap} "
          f"skip-pages={args.skip_pages} concurrency={args.concurrency}\n",
          flush=True)

    # Step 1: build all (act, page_start, page_end, text) chunks across all acts.
    all_chunks: list[tuple[str, int, int, int, str]] = []   # (act_name, max_section, ps, pe, text)
    for a in chosen:
        meta = ACTS[a]
        path = pdf_dir / meta["file"]
        if not path.exists():
            print(f"⚠  {meta['name']} skipped — {path} not found")
            continue
        pages = extract_pages(path, skip_pages=args.skip_pages)
        if args.limit_pages:
            pages = pages[: args.limit_pages]
        chunks = chunk_pages(pages, pages_per_chunk=args.pages_per_chunk, overlap=args.overlap)
        print(f"→ {meta['name']:5s}  {len(pages)} pages → {len(chunks)} chunks",
              flush=True)
        for ps, pe, txt in chunks:
            all_chunks.append((meta["name"], meta["max_section"], ps, pe, txt))

    if not all_chunks:
        raise SystemExit("Nothing to parse.")

    print(f"\nTotal chunks across acts: {len(all_chunks)}", flush=True)

    # Step 2: parallel LLM calls.
    llm = get_llm()
    sem = asyncio.Semaphore(args.concurrency)
    raw_sections: list[dict] = []
    failed = 0
    completed = 0
    t0 = time.perf_counter()

    async def worker(act_name: str, max_section: int, ps: int, pe: int, txt: str) -> None:
        nonlocal completed, failed
        async with sem:
            try:
                secs = await parse_chunk(llm, act_name=act_name,
                                         page_start=ps, page_end=pe, text=txt)
                raw_sections.extend(secs)
            except Exception:
                failed += 1
            completed += 1
            if completed % 5 == 0 or completed == len(all_chunks):
                elapsed = time.perf_counter() - t0
                rate = completed / max(elapsed, 0.1)
                eta = (len(all_chunks) - completed) / max(rate, 0.1)
                print(f"   {completed}/{len(all_chunks)} chunks  "
                      f"({rate:.1f}/s, eta {eta:.0f}s, failed={failed}, "
                      f"sections seen={len(raw_sections)})", flush=True)

    await asyncio.gather(*(worker(an, ms, ps, pe, txt) for an, ms, ps, pe, txt in all_chunks))

    # Step 3: stitch per act.
    final: list[dict] = []
    for a in chosen:
        meta = ACTS[a]
        act_sections = [s for s in raw_sections if s["act"] == meta["name"]]
        stitched = stitch(act_sections, max_section=meta["max_section"])
        nums = [int(s["number"]) for s in stitched]
        if nums:
            gaps: list[int] = []
            for prev, nxt in zip(nums, nums[1:]):
                if nxt - prev > 1:
                    gaps.append(prev + 1)
            print(f"\n=== {meta['name']} ===  {len(stitched)} sections "
                  f"(range {min(nums)}-{max(nums)})")
            if gaps:
                preview = ", ".join(str(g) for g in gaps[:10])
                more = f"  +{len(gaps) - 10} more" if len(gaps) > 10 else ""
                print(f"  missing: {preview}{more}")
            for s in stitched[:4]:
                print(f"  [{s['number']:>3}] {s['title_clean'][:80]}")
        else:
            print(f"\n=== {meta['name']} === 0 sections")
        final.extend(stitched)

    # Step 4: persist.
    out_path.write_text(json.dumps(final, indent=2, ensure_ascii=False))
    print(f"\n✓ wrote {len(final)} sections → {out_path}")
    print(f"\nNext: re-ingest in enriched mode")
    print(f"   docker compose exec backend python -m scripts.ingest_pdfs --enriched {out_path} --replace")


if __name__ == "__main__":
    asyncio.run(main())
