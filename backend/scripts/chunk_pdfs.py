"""Spatial-aware PDF chunker for Indian Gazette acts (BNS / BNSS / BSA).

Produces data/sections_parsed.json with clean per-section records.

Why this exists:
  The previous chunker (ingest_pdfs.py) had three bugs that contaminated the
  knowledge base:
    - SKIP_PAGES_DEFAULT=2 → lost sections 1 and 2 of every act
    - MARGIN_PCT_DEFAULT=0.18 (left-only) → lost 50%+ of titles AND treated
      left body indent as marginalia
    - dropped 8 consecutive BSA sections (109-116) — likely tight-packing bug

Visual inspection of the 3 PDFs (see commit message + chunker docs) revealed:
  - Marginalia ALTERNATES sides by page parity (gazette binding convention):
      odd display pages → RIGHT outer edge
      even display pages → LEFT outer edge
  - Two distinct marginalia types live on the page:
      (A) Title captions ("Definitions.", "Burden of proof.") on outer edge
      (B) Cross-reference annotations ("40 of 2019.") on either side, pattern
          ``\\d+ of \\d{4}\\.`` -- link to other statutes
  - Section starts: bold "N." at body left edge (x≈118), strictly increasing
  - Chapter headers: centered (x_mid≈300), "PART/CHAPTER ..."  — skip
  - Page headers: y<60 containing "GAZETTE OF INDIA" — skip

Pipeline:
  1. Per page, get_text("blocks") gives (x0,y0,x1,y1,text,block_no,block_type)
  2. Classify each block by spatial role + parity-aware marginalia side
  3. Section starts on body blocks matching ^\\s*(\\d{1,3})\\.\\s, strictly +1
  4. Cross-page concatenation walks blocks forward until next section header
  5. Title attribution: marginal caption with closest y-center to section header
  6. Cross-references: separate `cross_references_pdf` list per section
  7. Validate: counts match expected, all numbers present, no gaps silently lost

Usage:
  docker exec -w /app nyaya-backend python -m scripts.chunk_pdfs
  docker exec -w /app nyaya-backend python -m scripts.chunk_pdfs --acts BSA --debug
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf  # noqa: E402

# ---------------------------------------------------------------------------
# Per-act configuration
# ---------------------------------------------------------------------------

ACTS = {
    "BNS":  {"file": "bns.pdf",  "expected_sections": 358},
    "BNSS": {"file": "bnss.pdf", "expected_sections": 531},
    "BSA":  {"file": "bsa.pdf",  "expected_sections": 170},
}

# Spatial constants — all PDFs are 595 x 842 pt (A4 portrait).
PAGE_HEADER_Y_MAX  = 80     # y0 < this  → page header / page number
PAGE_FOOTER_Y_MIN  = 790    # y0 > this  → footer
BODY_X_MIN         = 115    # body column left edge
BODY_X_MAX         = 480    # body column right edge (text doesn't extend past)
MARGIN_RIGHT_X_MIN = 478    # right-side marginalia starts at outer column
MARGIN_LEFT_X_MAX  = 115    # left-side marginalia: right edge sits at body left
MARGINALIA_MAX_W   = 130    # marginalia blocks are narrow (≤130 pt wide)
TITLE_Y_SLACK      = 30     # title marginalia must be within ±this of section
                            #   header y. Section bodies are often >20 lines so
                            #   the caption is usually within ±15 of the header,
                            #   but we leave margin for tight-packed sections.
CHAPTER_X_CENTER   = (270, 330)  # centered headers fall in this x_mid range

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

RE_SECTION_HEADER = re.compile(r"^\s*(\d{1,3})\.\s*")   # period + optional whitespace
RE_CROSS_REF      = re.compile(r"^\s*(\d+)\s+of\s+(\d{4})\.\s*$")
RE_CHAPTER_PART   = re.compile(r"^\s*(PART|CHAPTER)\b", re.IGNORECASE)
RE_GAZETTE_HEADER = re.compile(r"GAZETTE\s+OF\s+INDIA", re.IGNORECASE)
RE_DIGITS_ONLY    = re.compile(r"^\s*\d+\s*$")    # bare page numbers
# Schedules + appendices appear after the last numbered section. They contain
# forms ("WARRANT FOR ARREST"), tables, etc. that share visual style with body
# text but are NOT sections. Once we hit one of these markers, stop parsing.
RE_END_OF_SECTIONS = re.compile(
    r"^\s*(?:THE\s+)?(?:FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH)?\s*SCHEDULE\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Block:
    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    page_idx: int     # 0-based PDF page index

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def x_center(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def y_center(self) -> float:
        return (self.y0 + self.y1) / 2


@dataclass
class Section:
    act: str
    number: str
    title: str = ""
    body_chunks: list[str] = field(default_factory=list)
    cross_refs: list[str] = field(default_factory=list)

    @property
    def body(self) -> str:
        return " ".join(c.strip() for c in self.body_chunks if c.strip())


# ---------------------------------------------------------------------------
# Block classification per page (parity-aware)
# ---------------------------------------------------------------------------

def is_odd_display_page(pdf_index: int) -> bool:
    """First content page (PDF idx 0) is printed page 1 → odd → RIGHT marginalia.

    All 3 gazette PDFs start on a content page (no cover insert), so PDF index
    maps directly to display page parity.
    """
    return pdf_index % 2 == 0


def classify_block(b: Block, pdf_index: int) -> str:
    """Return one of: header, footer, chapter, title_marg, cross_ref, body, ignore."""
    txt = b.text.strip()
    if not txt:
        return "ignore"

    # Page header / page number at top
    if b.y0 < PAGE_HEADER_Y_MAX:
        return "header"
    if RE_GAZETTE_HEADER.search(txt):
        return "header"
    if RE_DIGITS_ONLY.match(txt) and b.y0 < 100 and b.width < 30:
        return "header"          # stray page number

    # Footer (rarely populated in these gazette PDFs, but be safe)
    if b.y0 > PAGE_FOOTER_Y_MIN:
        return "footer"

    # Chapter / Part / centered all-caps headers (e.g. "ARREST OF PERSONS")
    is_centered = CHAPTER_X_CENTER[0] <= b.x_center <= CHAPTER_X_CENTER[1]
    is_short_caps = txt.isupper() and len(txt) < 80
    if is_centered and (RE_CHAPTER_PART.match(txt) or is_short_caps):
        return "chapter"

    # Cross-reference annotation (works on either side, distinctive pattern)
    if RE_CROSS_REF.match(txt):
        return "cross_ref"

    # Title marginalia by page parity
    odd = is_odd_display_page(pdf_index)
    if odd and b.x0 >= MARGIN_RIGHT_X_MIN and b.width < MARGINALIA_MAX_W:
        return "title_marg"
    if (not odd) and b.x1 <= MARGIN_LEFT_X_MAX + 5 and b.width < MARGINALIA_MAX_W:
        return "title_marg"

    # Body column (left edge within body range)
    if BODY_X_MIN <= b.x0 <= BODY_X_MAX:
        return "body"

    return "ignore"


# ---------------------------------------------------------------------------
# Parse one act PDF → list[Section]
# ---------------------------------------------------------------------------

def parse_act(pdf_path: Path, act: str, expected: int, debug: bool = False) -> list[Section]:
    doc = pymupdf.open(pdf_path)
    sections: list[Section] = []
    current: Section | None = None
    expected_next = 1

    # Walk pages in order. For each page, classify blocks, then walk body blocks
    # in reading order (y first, then x).
    end_of_sections = False
    for pidx in range(doc.page_count):
        if end_of_sections:
            break
        page = doc[pidx]
        # Quick scan: if this page contains "THE FIRST SCHEDULE" etc., stop.
        if RE_END_OF_SECTIONS.search(page.get_text() or ""):
            print(f"  STOP: hit schedule/appendix on PDF page {pidx + 1}", file=sys.stderr)
            end_of_sections = True
            break
        raw = page.get_text("blocks")
        classified: list[tuple[Block, str]] = []
        for rb in raw:
            # rb = (x0, y0, x1, y1, text, block_no, block_type)
            block_type = rb[6] if len(rb) > 6 else 0
            if block_type != 0:
                continue   # skip image blocks
            b = Block(x0=rb[0], y0=rb[1], x1=rb[2], y1=rb[3],
                      text=rb[4], page_idx=pidx)
            cls = classify_block(b, pidx)
            classified.append((b, cls))

        # Sort by reading order (top-to-bottom, left-to-right)
        classified.sort(key=lambda x: (round(x[0].y0 / 6), x[0].x0))

        title_margs = [b for b, c in classified if c == "title_marg"]
        cross_refs  = [b for b, c in classified if c == "cross_ref"]
        body_blocks = [b for b, c in classified if c == "body"]

        if debug:
            print(f"\n--- {act} page {pidx + 1} (parity={'odd' if is_odd_display_page(pidx) else 'even'}) ---", file=sys.stderr)
            print(f"  body={len(body_blocks)} title_marg={len(title_margs)} cross_ref={len(cross_refs)}", file=sys.stderr)

        # Walk each body block LINE-BY-LINE — PyMuPDF often merges multiple
        # sections into one block when they're vertically adjacent, so we must
        # scan inside the block, not just at its start.
        for b in body_blocks:
            lines = b.text.split("\n")
            # Approximate y for each line: linear interp across block height.
            n_lines = max(len(lines), 1)
            line_height = (b.y1 - b.y0) / n_lines
            for i, raw_line in enumerate(lines):
                line = raw_line.strip()
                if not line:
                    continue
                line_y = b.y0 + (i + 0.5) * line_height
                m = RE_SECTION_HEADER.match(line)
                if m:
                    num = int(m.group(1))
                    if num == expected_next:
                        if current is not None:
                            sections.append(current)
                        current = Section(act=act, number=str(num))
                        expected_next = num + 1
                        body_part = line[m.end():].strip()
                        if body_part:
                            current.body_chunks.append(body_part)
                        # Title attribution: closest marginalia by y
                        best, best_dy = None, TITLE_Y_SLACK
                        for tm in title_margs:
                            dy = abs(tm.y_center - line_y)
                            if dy < best_dy:
                                best_dy, best = dy, tm
                        if best is not None:
                            current.title = " ".join(best.text.split()).rstrip(".")
                        continue
                    elif num < expected_next:
                        # Back-reference within body ("see section 5") — body text.
                        pass
                    else:
                        # GAP — log and treat as body so downstream isn't shifted.
                        print(
                            f"  GAP: expected {expected_next}, found {num} on PDF page {pidx + 1}",
                            file=sys.stderr,
                        )

                if current is not None:
                    current.body_chunks.append(line)

        # Attribute cross-references to the current section. Cross-refs almost
        # always appear adjacent to the body line that mentions the other Act,
        # so the "current section at the time we hit the cross_ref on this page"
        # is the right owner.
        for cr in cross_refs:
            if current is not None:
                current.cross_refs.append(cr.text.strip())

    if current is not None:
        sections.append(current)

    doc.close()

    # Validation report
    found = sorted(int(s.number) for s in sections)
    expected_set = set(range(1, expected + 1))
    missing = sorted(expected_set - set(found))
    extra   = sorted(set(found) - expected_set)
    print(f"\n[{act}] parsed {len(sections)} sections, {len(missing)} missing, {len(extra)} extra")
    if missing:
        print(f"  missing: {missing[:30]}{'...' if len(missing) > 30 else ''}")
    if extra:
        print(f"  extra:   {extra[:30]}")

    return sections


# ---------------------------------------------------------------------------
# Output + acceptance tests
# ---------------------------------------------------------------------------

def run_acceptance_tests(records: list[dict]) -> list[str]:
    """Return list of failure messages (empty if all pass)."""
    failures: list[str] = []

    by_act: dict[str, list[dict]] = {}
    for r in records:
        by_act.setdefault(r["act"], []).append(r)

    for act, expected in [("BNS", 358), ("BNSS", 531), ("BSA", 170)]:
        recs = by_act.get(act, [])
        nums = {int(r["number"]) for r in recs if str(r["number"]).isdigit()}
        # Coverage
        coverage = len(nums) / expected
        if coverage < 0.99:
            failures.append(f"{act}: coverage {coverage:.1%} < 99% ({len(nums)}/{expected})")
        # Specific known-canonical sections that MUST be present
        canonical = {
            "BNS":  [1, 2, 202, 303, 358],
            "BNSS": [1, 2, 35, 173, 531],
            "BSA":  [1, 2, 109, 116, 119, 170],
        }[act]
        miss = [n for n in canonical if n not in nums]
        if miss:
            failures.append(f"{act}: missing canonical sections {miss}")
        # Body-quality checks
        for r in recs:
            body = r.get("raw_body", "") or ""
            if not body:
                failures.append(f"{act} §{r['number']}: empty body")
                continue
            if len(body) < 20:
                failures.append(f"{act} §{r['number']}: body too short ({len(body)} chars)")
            # Detect "runaway" sections — bodies > 50k chars usually mean the
            # parser merged multiple sections (failed to find a downstream
            # section header, dumped everything onto this one).
            if len(body) > 50_000:
                failures.append(f"{act} §{r['number']}: body suspiciously long ({len(body)} chars) — possible merge")

    return failures


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf-dir", default="/app/data")
    parser.add_argument("--out",      default="/app/data/sections_parsed.json")
    parser.add_argument("--acts",     default="BNS,BNSS,BSA")
    parser.add_argument("--debug",    action="store_true")
    args = parser.parse_args()

    pdf_dir = Path(args.pdf_dir)
    out_path = Path(args.out)

    all_records: list[dict] = []
    for act in [a.strip().upper() for a in args.acts.split(",")]:
        cfg = ACTS.get(act)
        if not cfg:
            print(f"unknown act: {act}", file=sys.stderr)
            continue
        pdf_path = pdf_dir / cfg["file"]
        if not pdf_path.exists():
            print(f"missing PDF: {pdf_path}", file=sys.stderr)
            continue
        sections = parse_act(pdf_path, act, cfg["expected_sections"], debug=args.debug)
        for s in sections:
            all_records.append({
                "act":                  s.act,
                "number":               s.number,
                "raw_title":            s.title,
                "raw_body":             s.body,
                "cross_references_pdf": s.cross_refs,
            })

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(all_records, f, indent=2, ensure_ascii=False)

    print(f"\nWrote {len(all_records)} sections to {out_path}")

    print("\n=== ACCEPTANCE TESTS ===")
    failures = run_acceptance_tests(all_records)
    if not failures:
        print("ALL PASS — chunker output is clean.")
    else:
        print(f"{len(failures)} failures:")
        for f in failures[:50]:
            print(f"  ✗ {f}")
        if len(failures) > 50:
            print(f"  ... and {len(failures) - 50} more")
        sys.exit(1)


if __name__ == "__main__":
    main()
