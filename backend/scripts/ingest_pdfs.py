"""Full ingest of BNS / BNSS / BSA PDFs into Pinecone (PyMuPDF-based).

Why PyMuPDF (and not pdfplumber):
  Indian Gazette PDFs are TWO-COLUMN. Short section titles live in a left
  margin (~12-15% of page width), the body text is in the main column.
  Default extractors merge both columns onto the same line, so a section
  reads "Punishments.    4. The punishments to which offenders..." and any
  `^\\d+\\.` regex misses the section start entirely.

  PyMuPDF exposes word-level bounding boxes, so we can:
    1. CLIP each page into two regions by x-coordinate
    2. Extract body text cleanly (regex now matches section starts)
    3. Extract marginalia separately and map it back to each section by
       y-coordinate → we get the *real* section title ("Punishments",
       "Commutation of sentence", "Culpable homicide") instead of
       synthesising it from body words.

Pipeline:
  1. For each PDF in `data/`:
       - clip per page into marginalia (left) and body (right)
       - reconstruct body text and locate section starts via regex on
         a strictly-increasing N. sequence within the act's known range
       - for each section, look up nearby marginalia (same page, y within
         a tolerance of the section number's y) → that's the title
  2. Embed each section's text via Ollama (`nomic-embed-text`, 768-dim)
  3. Upsert into Pinecone with metadata:
       { act, category, section_number, section_title, pageContent }

Run inside the backend container (so Ollama is reachable at host.docker.internal):

    docker compose exec backend python -m scripts.ingest_pdfs --dry-run

Useful flags:
    --acts bns,bnss,bsa   subset of acts to ingest (default: all three)
    --dry-run             parse + print summary, don't touch Pinecone
    --batch N             upsert batch size (default 16)
    --pdf-dir PATH        where to find the PDFs (default /app/data)
    --skip-pages N        pages to skip at the start of each PDF (default 2)
    --margin-pct F        left fraction of page treated as marginalia
                          (default 0.13 = 13%)
    --replace             delete existing vectors per act before re-ingest
    --debug               dump body + marginalia preview per act
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pymupdf  # noqa: E402

from app.config import settings  # noqa: E402
from app.services.embeddings import embed_texts  # noqa: E402

# ---------------------------------------------------------------------------
# Act metadata
# ---------------------------------------------------------------------------

ACTS = {
    "bns":  {"file": "bns.pdf",  "name": "BNS",  "category": "Criminal_Laws",
             "max_section": 360},
    "bnss": {"file": "bnss.pdf", "name": "BNSS", "category": "Procedural_Law",
             "max_section": 540},
    "bsa":  {"file": "bsa.pdf",  "name": "BSA",  "category": "Evidence_Law",
             "max_section": 175},
}

SKIP_PAGES_DEFAULT = 2
MARGIN_PCT_DEFAULT = 0.18     # fallback only — auto-detected per page from
                              # the largest horizontal gap in word x-centers
TITLE_Y_SLACK = 6.0           # pt; allowed slack when matching section y to
                              # marginalia y-range (handles font baseline jitter)
MAX_SECTION_CHARS = 1800


# ---------------------------------------------------------------------------
# Line + text reconstruction from word-level bbox data
# ---------------------------------------------------------------------------

@dataclass
class Word:
    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    page: int        # 0-indexed
    y_mid: float = 0.0

    def __post_init__(self) -> None:
        self.y_mid = (self.y0 + self.y1) / 2.0


def _words_from_page(page: pymupdf.Page, page_idx: int) -> list[Word]:
    out: list[Word] = []
    for x0, y0, x1, y1, txt, *_ in page.get_text("words"):
        if txt and txt.strip():
            out.append(Word(x0=x0, y0=y0, x1=x1, y1=y1, text=txt,
                            page=page_idx))
    return out


def _group_lines(words: list[Word], y_tol: float = 3.0) -> list[list[Word]]:
    """Group words on the same baseline (same y) into lines, sorted left-to-right."""
    if not words:
        return []
    by_y = sorted(words, key=lambda w: (w.page, w.y_mid, w.x0))
    lines: list[list[Word]] = []
    cur: list[Word] = [by_y[0]]
    for w in by_y[1:]:
        last = cur[-1]
        if w.page == last.page and abs(w.y_mid - last.y_mid) <= y_tol:
            cur.append(w)
        else:
            lines.append(sorted(cur, key=lambda v: v.x0))
            cur = [w]
    lines.append(sorted(cur, key=lambda v: v.x0))
    return lines


def _line_text(line: list[Word]) -> str:
    return " ".join(w.text for w in line)


# ---------------------------------------------------------------------------
# Page → (body lines, marginalia entries)
# ---------------------------------------------------------------------------

@dataclass
class MarginEntry:
    page: int
    y_top: float
    y_bot: float
    text: str

    @property
    def y_mid(self) -> float:
        return (self.y_top + self.y_bot) / 2.0


def _detect_gutter(words: list[Word], page_w: float, fallback: float) -> float:
    """Auto-detect the x-coordinate of the gutter between marginalia and body.

    Strategy: collect unique word x-centers, look at those in the LEFT
    third of the page, find the largest horizontal gap. That gap is
    almost always the marginalia/body gutter. Falls back to `fallback`
    when the page has no marginalia or the layout is unusual.
    """
    centers = sorted({round((w.x0 + w.x1) / 2.0) for w in words})
    left = [c for c in centers if c < page_w * 0.35]
    if len(left) < 4:
        return fallback
    best_gap = 0.0
    best_cut = fallback
    for a, b in zip(left, left[1:]):
        gap = b - a
        if gap > best_gap:
            best_gap = gap
            best_cut = (a + b) / 2.0
    # A real gutter is usually >= 18pt. Anything smaller is just inter-word
    # spacing inside the body column — trust the fallback in that case.
    if best_gap >= 18:
        return best_cut
    return fallback


def split_page(
    page: pymupdf.Page, page_idx: int, margin_pct: float,
) -> tuple[list[list[Word]], list[MarginEntry]]:
    """Return (body_lines, marginalia_entries) for this page.

    Column boundary is AUTO-DETECTED per page (largest x-gap in the left
    third) with `margin_pct` as a fallback. This handles the fact that
    Indian gazette PDFs use a wider marginalia column on some pages than
    others — a fixed percentage either drops marginalia words on the right
    edge or pulls body words into the marginalia.

    Word column assignment uses the word's CENTER x: a word whose center
    is left of the cutoff is marginalia, otherwise body. This avoids
    dropping boundary-straddling words like a section number that sits
    right at the gutter.
    """
    page_w = float(page.rect.width)
    fallback_cut = page_w * margin_pct
    all_words = _words_from_page(page, page_idx)
    cutoff = _detect_gutter(all_words, page_w, fallback_cut)

    margin_words: list[Word] = []
    body_words: list[Word] = []
    for w in all_words:
        x_center = (w.x0 + w.x1) / 2.0
        if x_center < cutoff:
            margin_words.append(w)
        else:
            body_words.append(w)

    body_lines = _group_lines(body_words)

    # Marginalia: keep one entry per raw line (no pre-merge). We assemble
    # full titles later by gathering all entries in the y-range between
    # consecutive section starts — that's far more robust than relying on
    # a gap-threshold merge that either glues two titles or splits one.
    margin_lines = _group_lines(margin_words)
    entries: list[MarginEntry] = []
    for ln in margin_lines:
        text = _line_text(ln).strip()
        if not text:
            continue
        top = min(w.y0 for w in ln)
        bot = max(w.y1 for w in ln)
        entries.append(MarginEntry(
            page=page_idx, y_top=top, y_bot=bot, text=text,
        ))
    return body_lines, entries


# ---------------------------------------------------------------------------
# Header / footer scrubbing on body text
# ---------------------------------------------------------------------------

RUNNING_HEADER_RES = [
    re.compile(r"(?i)^\s*THE\s+GAZETTE\s+OF\s+INDIA"),
    re.compile(r"(?i)^\s*\[?\s*Part\s+[IVX]+"),
    re.compile(r"(?i)^\s*Sec\.?\s*\d+\s*\]"),
    re.compile(r"(?i)^\s*THE\s+BHARATIYA[^\n]+(SANHITA|ADHINIYAM)"),
    re.compile(r"(?i)^\s*CHAPTER\s+[IVXLC]+\s*$"),
    re.compile(r"(?i)^\s*OF\s+[A-Z][A-Z\s,]{2,}\s*$"),
    re.compile(r"^\s*\d{1,4}\s*$"),                 # bare page numbers
    re.compile(r"^\s*\d{1,3}\s+of\s+\d{4}\.?\s*$"),  # "10 of 1897." references
]


def _is_running_header(s: str) -> bool:
    s = s.strip()
    if not s:
        return True
    for pat in RUNNING_HEADER_RES:
        if pat.match(s):
            return True
    return False


# ---------------------------------------------------------------------------
# Section detection
# ---------------------------------------------------------------------------

# Permissive: section start can appear at line-start OR after an optional
# marginalia-bleed prefix (e.g., "of punishment. 6. In calculating...").
# We require a Capital letter or "(" after the "N. " to filter false hits.
SECTION_START_RE = re.compile(
    r"(?:^|(?<=\s))(\d{1,3})\.\s+([A-Z(].{0,400})$"
)


@dataclass
class SectionMatch:
    number: int
    page: int
    y_mid: float
    line_idx: int          # index into the flat list of body lines
    first_line_text: str   # text after the "N. " prefix


def find_section_starts(
    body_lines: list[list[Word]], *, max_section: int,
) -> list[SectionMatch]:
    """Pick out strictly-increasing N. sequence within the act's range."""
    candidates: list[SectionMatch] = []
    for idx, line in enumerate(body_lines):
        text = _line_text(line)
        if _is_running_header(text):
            continue
        m = SECTION_START_RE.search(text)
        if not m:
            continue
        n = int(m.group(1))
        if not (1 <= n <= max_section):
            continue
        # Find the y of the section number's own word (not the line's average,
        # in case marginalia bled in and shifted line[0].y_mid).
        sec_y = line[0].y_mid
        for w in line:
            if w.text.rstrip(".") == str(n):
                sec_y = w.y_mid
                break
        candidates.append(SectionMatch(
            number=n,
            page=line[0].page,
            y_mid=sec_y,
            line_idx=idx,
            first_line_text=m.group(2).strip(),
        ))

    accepted: list[SectionMatch] = []
    last_n = 0
    for c in candidates:
        if c.number <= last_n:
            continue
        accepted.append(c)
        last_n = c.number
    return accepted


# ---------------------------------------------------------------------------
# Title resolution: marginalia first, then inline "Title.—body", then synth
# ---------------------------------------------------------------------------

INLINE_TITLE_RE = re.compile(
    r"^(.{2,120}?)(?:\.\s*[—–]+|\.\s*-{2,}|:\s*[—–]+|\s+—\s+)"
)


def _clean_title(raw: str) -> str:
    t = raw.strip().rstrip(".:—–-").strip()
    t = re.sub(r"\s+", " ", t)
    return t


def _title_from_marginalia_range(
    section: SectionMatch,
    next_section: SectionMatch | None,
    marginalia: list[MarginEntry],
) -> str | None:
    """Concat all marginalia lines on this section's page that fall in the
    y-band [section.y - slack, next_section.y - slack].

    If next_section is on a different page (or this is the last section),
    take everything from section.y down to bottom of page.
    """
    same_page = [m for m in marginalia if m.page == section.page]
    upper = section.y_mid - TITLE_Y_SLACK
    if next_section is not None and next_section.page == section.page:
        lower = next_section.y_mid - TITLE_Y_SLACK
    else:
        lower = float("inf")

    own = [m for m in same_page if upper <= m.y_top <= lower]
    if not own:
        return None
    own.sort(key=lambda m: (m.y_top, m.text))
    joined = " ".join(m.text for m in own)
    title = _clean_title(joined)
    if 2 < len(title) < 280:
        return title
    return None


def _title_for(
    section: SectionMatch,
    next_section: SectionMatch | None,
    marginalia: list[MarginEntry],
    body_preview: str = "",
) -> str:
    # 1. Real marginalia title gathered from the y-band for this section.
    t = _title_from_marginalia_range(section, next_section, marginalia)
    if t and not t[0].isdigit():
        return t

    # 2. Inline title "Murder.—Whoever..." in the body's first line.
    m = INLINE_TITLE_RE.match(section.first_line_text)
    if m:
        title = _clean_title(m.group(1))
        if 2 < len(title) < 120 and not title[0].isdigit():
            return title

    # 3. Synth from a richer body preview.
    src = body_preview.strip() or section.first_line_text
    words = src.split()[:14]
    title = " ".join(words).strip()
    if len(title) > 110:
        title = title[:107].rstrip() + "…"
    return title or f"Section {section.number}"


# ---------------------------------------------------------------------------
# Section body assembly
# ---------------------------------------------------------------------------

@dataclass
class Section:
    act: str
    category: str
    number: str
    title: str
    text: str

    def to_record(self) -> dict:
        body = self.text[:MAX_SECTION_CHARS]
        return {
            "id": f"{self.act}_{self.number}",
            "metadata": {
                "act": self.act,
                "category": self.category,
                "section_number": self.number,
                "section_title": self.title.strip(),
                "pageContent": body,
            },
            "embed_text": f"{self.title.strip()}. {body}",
        }


def assemble_sections(
    body_lines: list[list[Word]],
    sections: list[SectionMatch],
    marginalia: list[MarginEntry],
    *,
    act_name: str,
    category: str,
) -> list[Section]:
    """Build Section objects by slicing body_lines between successive starts."""
    out: list[Section] = []
    for i, sec in enumerate(sections):
        start = sec.line_idx
        end = sections[i + 1].line_idx if i + 1 < len(sections) else len(body_lines)
        chunk: list[str] = []
        for line in body_lines[start:end]:
            text = _line_text(line)
            if _is_running_header(text):
                continue
            chunk.append(text)
        body = "\n".join(chunk).strip()
        if len(body) < 30:
            continue
        body_preview = re.sub(r"^\s*\d{1,3}\.\s+", "", body, count=1)[:300]
        nxt = sections[i + 1] if i + 1 < len(sections) else None
        title = _title_for(sec, nxt, marginalia, body_preview=body_preview)
        out.append(Section(
            act=act_name, category=category,
            number=str(sec.number), title=title, text=body,
        ))
    return out


# ---------------------------------------------------------------------------
# Top-level PDF → sections
# ---------------------------------------------------------------------------

@dataclass
class ParsedPdf:
    body_lines: list[list[Word]] = field(default_factory=list)
    marginalia: list[MarginEntry] = field(default_factory=list)


def parse_pdf(
    pdf_path: Path, *, skip_pages: int, margin_pct: float,
) -> ParsedPdf:
    parsed = ParsedPdf()
    with pymupdf.open(pdf_path) as doc:
        for page_idx in range(skip_pages, doc.page_count):
            page = doc[page_idx]
            body_lines, margin_entries = split_page(page, page_idx, margin_pct)
            parsed.body_lines.extend(body_lines)
            parsed.marginalia.extend(margin_entries)
    return parsed


# ---------------------------------------------------------------------------
# Pinecone
# ---------------------------------------------------------------------------

def pinecone_index():
    from pinecone import Pinecone
    pc = Pinecone(api_key=settings.pinecone_api_key)
    return pc.Index(settings.pinecone_index)


def delete_act_vectors(index, act_name: str) -> None:
    try:
        index.delete(filter={"act": {"$eq": act_name}})
        print(f"   ✗ cleared existing vectors for act={act_name}")
    except Exception as exc:
        print(f"   ! could not clear existing {act_name} vectors: {exc}")


async def upsert_records(index, records: list[dict], batch: int) -> None:
    texts = [r["embed_text"] for r in records]
    print(f"   embedding {len(texts)} chunks via "
          f"{settings.embeddings_provider}/{settings.embeddings_model}…",
          flush=True)
    vectors = await embed_texts(texts)
    if not vectors or len(vectors[0]) != settings.embeddings_dim:
        raise SystemExit(
            f"   ✗ embedding dim mismatch: got {len(vectors[0]) if vectors else 0}, "
            f"Pinecone index expects {settings.embeddings_dim}. Check EMBEDDINGS_MODEL."
        )
    payload = [{
        "id": r["id"],
        "values": v,
        "metadata": r["metadata"],
    } for r, v in zip(records, vectors)]
    for i in range(0, len(payload), batch):
        index.upsert(vectors=payload[i:i + batch])
        print(f"   ↑ {min(i + batch, len(payload))}/{len(payload)} upserted",
              flush=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def enriched_to_records(enriched: list[dict]) -> list[dict]:
    """Turn each enriched section into MULTIPLE Pinecone vectors.

    Per section we emit (default 6 vectors):
      <act>_<n>_main : title_clean + summary + key_terms   (semantic anchor)
      <act>_<n>_q1..q5: one vector per hypothetical question (query surface)

    All share `section_number` in metadata so rag.py dedupes by section_number
    when assembling the final citation list. This multiplies retrieval surface
    area ~6x per section for the same Pinecone index.
    """
    out: list[dict] = []
    for r in enriched:
        act      = r["act"]
        num      = r["number"]
        title    = (r.get("title_clean") or "").strip() or f"Section {num}"
        summary  = (r.get("summary") or "").strip()
        body     = (r.get("raw_body") or "")[:MAX_SECTION_CHARS]
        key_terms = ", ".join(r.get("key_terms") or [])
        punishment = (r.get("punishment") or "").strip()
        cat = next((ACTS[a]["category"] for a in ACTS if ACTS[a]["name"] == act), "")

        # Shared metadata so rag.py / verifier.py work without changes.
        base_meta = {
            "act":             act,
            "category":        cat,
            "section_number":  num,
            "section_title":   title,
            "pageContent":     body,
            "summary":         summary,
            "punishment":      punishment,
        }

        # 1) Semantic anchor — title + summary + key terms (+ punishment if any)
        anchor_text = ". ".join(filter(None, [
            title, summary, key_terms,
            f"Punishment: {punishment}" if punishment else "",
        ]))
        out.append({
            "id": f"{act}_{num}_main",
            "metadata": {**base_meta, "chunk_kind": "anchor"},
            "embed_text": anchor_text,
        })

        # 2) One vector per hypothetical question.
        for i, q in enumerate(r.get("hypothetical_questions") or [], start=1):
            out.append({
                "id": f"{act}_{num}_q{i}",
                "metadata": {**base_meta, "chunk_kind": "hypo_q", "chunk_text": q},
                "embed_text": q,
            })
    return out


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--acts", default="bns,bnss,bsa")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--batch", type=int, default=16)
    parser.add_argument("--pdf-dir", default="/app/data")
    parser.add_argument("--skip-pages", type=int, default=SKIP_PAGES_DEFAULT)
    parser.add_argument("--margin-pct", type=float, default=MARGIN_PCT_DEFAULT)
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument(
        "--enriched", default=None,
        help="Path to sections_enriched.json. When set, skip PDF parsing "
             "and do multi-vector ingest (anchor + 5 hypothetical questions per section). "
             "Pair with --replace.",
    )
    args = parser.parse_args()

    # ----- Enriched mode: read JSON, multi-vector ingest, then return -----
    if args.enriched:
        enriched_path = Path(args.enriched)
        if not enriched_path.exists():
            raise SystemExit(f"Enriched JSON not found: {enriched_path}")
        enriched = json.loads(enriched_path.read_text())
        if args.acts != "bns,bnss,bsa":
            wanted = {ACTS[a.strip().lower()]["name"] for a in args.acts.split(",")
                      if a.strip().lower() in ACTS}
            enriched = [r for r in enriched if r.get("act") in wanted]

        records = enriched_to_records(enriched)
        by_act: dict[str, int] = {}
        for r in records:
            by_act[r["metadata"]["act"]] = by_act.get(r["metadata"]["act"], 0) + 1
        print(f"Enriched mode: {len(enriched)} sections → {len(records)} vectors",
              flush=True)
        for a, n in sorted(by_act.items()):
            print(f"   {a}: {n} vectors")

        if args.dry_run:
            print("\n--- sample (first 6 vectors) ---")
            for r in records[:6]:
                print(f"  [{r['id']:<14}] {r['embed_text'][:100]}")
            return

        print(f"\n→ embedding via {settings.embeddings_provider}/"
              f"{settings.embeddings_model} ({settings.embeddings_dim}-dim, "
              f"batch={args.batch})", flush=True)
        index = pinecone_index()
        if args.replace:
            for act_name in by_act:
                delete_act_vectors(index, act_name)
        await upsert_records(index, records, batch=args.batch)

        try:
            stats = index.describe_index_stats()
            total = stats.get("total_vector_count") if isinstance(stats, dict) \
                else getattr(stats, "total_vector_count", "?")
            print(f"\n✓ index '{settings.pinecone_index}' now holds {total} vectors",
                  flush=True)
        except Exception:
            pass
        print("\nNext: rebuild the graph + re-run eval:")
        print("    docker compose exec backend python -m scripts.build_graph")
        print("    docker compose exec backend python -m eval.runner")
        return

    pdf_dir = Path(args.pdf_dir)
    if not pdf_dir.exists():
        raise SystemExit(f"PDF dir not found: {pdf_dir}")

    chosen = [a.strip().lower() for a in args.acts.split(",") if a.strip()]
    for a in chosen:
        if a not in ACTS:
            raise SystemExit(f"unknown act '{a}'. choices: {','.join(ACTS)}")

    print(f"PDFs in {pdf_dir} | skip-pages={args.skip_pages} | "
          f"margin-pct={args.margin_pct}\n", flush=True)

    all_records: list[dict] = []
    by_act: dict[str, list[Section]] = {}
    for a in chosen:
        meta = ACTS[a]
        path = pdf_dir / meta["file"]
        if not path.exists():
            print(f"⚠  {meta['name']} skipped — {path} not found")
            continue
        size_kb = path.stat().st_size // 1024
        print(f"→ {meta['name']:5s}  {path.name}  ({size_kb} KB)")

        parsed = parse_pdf(path, skip_pages=args.skip_pages,
                           margin_pct=args.margin_pct)
        if args.debug:
            print(f"   debug: {len(parsed.body_lines)} body lines, "
                  f"{len(parsed.marginalia)} marginalia entries")
            print("   --- first 12 body lines (post-clip) ---")
            for ln in parsed.body_lines[:12]:
                print(f"     | {_line_text(ln)[:120]}")
            print("   --- first 8 marginalia entries ---")
            for m in parsed.marginalia[:8]:
                print(f"     | p{m.page} y={m.y_mid:.1f}  {m.text[:80]}")

        starts = find_section_starts(
            parsed.body_lines, max_section=meta["max_section"],
        )
        if not starts:
            print(f"   ✗ no sections matched — try --skip-pages 0 / --margin-pct 0.10 / --debug")
            continue

        sections = assemble_sections(
            parsed.body_lines, starts, parsed.marginalia,
            act_name=meta["name"], category=meta["category"],
        )
        if not sections:
            print(f"   ✗ section starts found but no bodies survived filter")
            continue

        nums = [int(s.number) for s in sections]
        gaps: list[int] = []
        for prev, nxt in zip(nums, nums[1:]):
            if nxt - prev > 1:
                gaps.append(prev + 1)
        print(f"   ✓ {len(sections)} sections  (range {min(nums)}–{max(nums)})")
        if gaps:
            preview = ", ".join(str(g) for g in gaps[:10])
            more = f"  +{len(gaps) - 10} more" if len(gaps) > 10 else ""
            print(f"     missing: {preview}{more}")
        by_act[a] = sections
        all_records.extend(s.to_record() for s in sections)

    if not all_records:
        raise SystemExit("Nothing to ingest.")

    print(f"\nTotal: {len(all_records)} sections to upsert\n", flush=True)

    if args.dry_run:
        for a, secs in by_act.items():
            print(f"\n=== {ACTS[a]['name']} ({len(secs)} sections) ===")
            for s in secs[:6]:
                print(f"  [{s.number:>3}] {s.title[:90]}")
            if len(secs) > 6:
                print(f"  …and {len(secs) - 6} more")
        return

    print(f"→ embedding via {settings.embeddings_provider}/{settings.embeddings_model}")
    print(f"   ({settings.embeddings_dim}-dim, batch={args.batch})", flush=True)

    index = pinecone_index()
    if args.replace:
        for a in by_act:
            delete_act_vectors(index, ACTS[a]["name"])

    await upsert_records(index, all_records, batch=args.batch)

    try:
        stats = index.describe_index_stats()
        total = stats.get("total_vector_count") if isinstance(stats, dict) \
            else getattr(stats, "total_vector_count", "?")
        print(f"\n✓ index '{settings.pinecone_index}' now holds {total} vectors",
              flush=True)
    except Exception:
        pass

    print("\nNext: rebuild the graph + re-run eval:")
    print("    docker compose exec backend python -m scripts.build_graph")
    print("    docker compose exec backend python -m eval.runner")


if __name__ == "__main__":
    asyncio.run(main())
