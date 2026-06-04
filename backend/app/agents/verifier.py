"""Citation verifier — the trust layer.

For every section an advocate cites, re-retrieve the real statute text and ask
the model whether the claim actually rests on that section. When the section
doesn't support the claim, the verifier also proposes what section probably
should have been cited (suggested_section).

What changed vs v1:
- Section-number regex now catches `BNS 303`, `BNSS 283(1)`, `s.303`, `Sec 303`,
  `Section 303`, and bare `303` immediately after an act keyword. Previous regex
  required the literal word "section", so any judgment that wrote `BNS 303(2)
  and 305` had its citations silently skipped.
- Verifier prompt is structured to elicit `{verified, note, suggested_section}`
  so wrong cites surface a helpful correction instead of a useless red badge.
- Multi-act dedup: `BNS 303` and `Section 303` mentioned in the same text are
  collapsed; we verify per (act, number) so cross-act sections with the same
  number don't clobber each other.
"""
from __future__ import annotations

import asyncio
import re

from app.core.llm import get_llm
from app.prompts.templates import VERIFIER
from app.schemas.models import Citation
from app.services.vector_store import search_sections


# All the ways an Indian-legal LLM tends to name a section in prose:
#   "section 303"  /  "Sec. 303"  /  "s. 303"  /  "S 303"
#   "BNS 303"  /  "BNSS 283(1)"  /  "BSA 24"
#   "section 303(2)"  /  "section 303(2) and 305"
_SECTION_PATTERNS = [
    re.compile(r"\b(?:section|sec\.?|s\.?)\s*(\d{1,3})\b", re.IGNORECASE),
    re.compile(r"\b(BNS|BNSS|BSA)\s*\.?\s*(?:section|sec\.?|s\.?)?\s*(\d{1,3})", re.IGNORECASE),
]


def extract_citations(text: str) -> list[tuple[str | None, str]]:
    """Return [(act_or_None, section_number)] pairs found in `text`, deduped."""
    if not text:
        return []
    found: list[tuple[str | None, str]] = []
    seen: set[tuple[str | None, str]] = set()

    # Pattern 1: bare "section N" — act unknown.
    for m in _SECTION_PATTERNS[0].finditer(text):
        key = (None, m.group(1))
        if key not in seen:
            seen.add(key)
            found.append(key)

    # Pattern 2: "BNS N" / "BNSS N" — act known, supersedes any bare (None, N).
    for m in _SECTION_PATTERNS[1].finditer(text):
        act = m.group(1).upper()
        num = m.group(2)
        # Replace any earlier (None, num) — we now know the act.
        for i, (a, n) in enumerate(found):
            if a is None and n == num:
                found[i] = (act, num)
                seen.discard((None, num))
                seen.add((act, num))
                break
        else:
            if (act, num) not in seen:
                seen.add((act, num))
                found.append((act, num))
    return found


async def verify_claim(claim: str, section_number: str, *, act: str | None = None) -> Citation:
    """Verify one citation. If `act` is known, scope the lookup to that act."""
    filters = {"act": act} if act else None
    matches = await search_sections(claim, top_k=1, section_number=section_number, filters=filters)
    if not matches and act:
        # Fall back to any-act lookup if filtered lookup missed.
        matches = await search_sections(claim, top_k=1, section_number=section_number)

    if not matches:
        return Citation(
            act=act or "",
            section_number=section_number,
            verified=False,
            verify_note="Section not found in the legal database.",
        )

    m = matches[0]
    verified, note, suggested = False, "Could not verify automatically.", None
    try:
        llm = get_llm()
        result = await llm.complete_json(
            [
                {"role": "system", "content": VERIFIER + "\n\n"
                    "Return ONLY JSON: {\"verified\": bool, \"note\": \"string\", "
                    "\"suggested_section\": \"BNS|BNSS|BSA N or null\"}. "
                    "If `verified` is false and you can guess what section the claim "
                    "really refers to, fill `suggested_section`; otherwise null."},
                {
                    "role": "user",
                    "content": (
                        f"CITED: {(m.get('act') or act or '').upper()} Section {section_number}\n"
                        f"SECTION TEXT:\n{m['text'][:1500]}\n\n"
                        f"CLAIM:\n{claim[:600]}"
                    ),
                },
            ],
            fast=True,
            max_tokens=220,
        )
        verified = bool(result.get("verified"))
        note = str(result.get("note", "")).strip() or note
        sug = result.get("suggested_section")
        if sug and not verified:
            suggested = str(sug).strip()
    except Exception:
        pass

    if suggested:
        note = f"{note} (likely meant: {suggested})".strip()

    return Citation(
        act=m["act"],
        section_number=m["section_number"],
        section_title=m["section_title"],
        score=m.get("score"),
        snippet=(m["text"] or "")[:400],
        verified=verified,
        verify_note=note,
    )


async def verify_text(claim_text: str) -> list[Citation]:
    """Verify every section cited in a block of text, concurrently."""
    cites = extract_citations(claim_text)
    if not cites:
        return []
    return await asyncio.gather(*(
        verify_claim(claim_text, num, act=act) for act, num in cites
    ))


# Kept for backwards compatibility with anything importing the old helper.
def extract_section_numbers(text: str) -> list[str]:
    return sorted({num for _, num in extract_citations(text)})
