"""End-to-end smoke test for all 4 production API endpoints.

Exercises:
  1. POST /api/assistant         → chat via the new query_planner
  2. POST /api/fir               → FIR drafter (uses retrieve_context directly)
  3. POST /api/investigation     → police investigation (retrieve_context)
  4. POST /api/cases/trial       → courtroom (retrieve_context × multiple agents)

For each, prints:
  - HTTP status + latency
  - Whether response contains IPC/CrPC/IEA (should be NONE — banned)
  - Whether citations are populated and from correct acts
  - For FIR: was a valid FIR text produced?
  - For investigation: applicable_sections present?
  - For trial: judgment populated? citations present?

Run inside the backend container (hits localhost — fastest):
  docker exec -w /app nyaya-backend python -m scripts.smoke_test_e2e

Or against production (slower, real deploy):
  docker exec -w /app nyaya-backend env API_BASE=https://nyaya-ai-backend-bfel.onrender.com \\
    python -m scripts.smoke_test_e2e

Expected wall time:
  - assistant: ~12-15s  (planner does 5-10 LLM calls)
  - fir:        ~10-15s
  - investigation: ~5-8s
  - trial:      ~30-60s (multi-agent)
  TOTAL: ~60-100s
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

API_BASE = os.environ.get("API_BASE", "http://localhost:8000").rstrip("/")
USER_ID = "smoke-user"
SESSION = f"smoke-{int(time.time())}"
TIMEOUT = httpx.Timeout(180.0)

BANNED_TERMS = ["IPC", "Indian Penal Code", "CrPC", "Code of Criminal Procedure",
                 "IEA", "Indian Evidence Act"]


def _check_banned(text: str, *, label: str) -> list[str]:
    """Return list of banned terms found in text (empty = clean)."""
    if not text:
        return []
    found = [t for t in BANNED_TERMS if t in text]
    return found


def _short(s: str, n: int = 240) -> str:
    if not s:
        return ""
    s = s.replace("\n", " ")
    return s + ("…" if len(s) > n else "")


async def test_assistant(client: httpx.AsyncClient) -> dict:
    print("\n========== 1. ASSISTANT (via planner) ==========")
    payload = {
        "chat_input": "what is the punishment for theft and what to do if my friend is arrested for it",
        "session_id": f"{SESSION}-assistant",
        "user_id": USER_ID,
    }
    t0 = time.perf_counter()
    r = await client.post(f"{API_BASE}/api/assistant", json=payload, timeout=TIMEOUT)
    dt = time.perf_counter() - t0
    print(f"  HTTP {r.status_code}  ({dt:.1f}s)")
    if r.status_code != 200:
        print(f"  body: {r.text[:300]}")
        return {"ok": False, "reason": f"HTTP {r.status_code}"}
    j = r.json()
    content = j.get("content", "")
    cites = j.get("citations", []) or []
    cite_pairs = [(c.get("act"), c.get("section_number")) for c in cites]
    banned = _check_banned(content, label="answer")
    print(f"  intent: {j.get('intent')}, low_conf: {j.get('low_confidence')}")
    print(f"  citations ({len(cites)}): {cite_pairs[:6]}")
    print(f"  banned terms in answer: {banned if banned else '(none — clean)'}")
    print(f"  answer[:300]: {_short(content, 300)}")
    return {
        "ok": r.status_code == 200 and not banned and bool(cites),
        "banned": banned,
        "cites": cite_pairs,
        "latency": dt,
    }


async def test_fir(client: httpx.AsyncClient) -> dict:
    print("\n========== 2. FIR DRAFT ==========")
    payload = {
        "session_id": f"{SESSION}-fir",
        "user_id": USER_ID,
        "complainant_name": "Vigilance Officer Sharma",
        "complainant_address": "Anti-Corruption Bureau, New Delhi",
        "complainant_phone": "9999000001",
        "complainant_age": "42",
        "complainant_gender": "M",
        "police_station": "Connaught Place",
        "incident_date": "2026-05-15",
        "incident_time": "16:00",
        "incident_location": "Government Quarters, Delhi",
        "accused": "Mr. Rajesh Kumar, Deputy Secretary, Ministry of Finance",
        "facts": (
            "Mr. Rajesh Kumar, a serving Deputy Secretary in the Ministry of Finance, "
            "has been operating a private import-export business in his wife's name "
            "since January 2025 in direct violation of his service rules. Bank records "
            "and witness statements confirm his active involvement. He has not obtained "
            "government sanction for this private business and continues to draw his "
            "government salary."
        ),
    }
    t0 = time.perf_counter()
    r = await client.post(f"{API_BASE}/api/fir", json=payload, timeout=TIMEOUT)
    dt = time.perf_counter() - t0
    print(f"  HTTP {r.status_code}  ({dt:.1f}s)")
    if r.status_code != 200:
        print(f"  body: {r.text[:300]}")
        return {"ok": False, "reason": f"HTTP {r.status_code}"}
    j = r.json()
    fir_text = j.get("fir_text", "")
    cites = j.get("citations", []) or []
    cite_pairs = [(c.get("act"), c.get("section_number")) for c in cites]
    banned = _check_banned(fir_text, label="fir_text")
    has_bns_202 = any(c.get("act") == "BNS" and str(c.get("section_number")) == "202"
                       for c in cites)
    print(f"  fir_text length: {len(fir_text)}")
    print(f"  citations ({len(cites)}): {cite_pairs[:5]}")
    print(f"  contains BNS §202 (expected for PS-trade case): {has_bns_202}")
    print(f"  banned terms in FIR: {banned if banned else '(none — clean)'}")
    print(f"  fir_text[:300]: {_short(fir_text, 300)}")
    return {
        "ok": r.status_code == 200 and not banned and len(fir_text) > 100,
        "banned": banned,
        "has_expected_section": has_bns_202,
        "cites": cite_pairs,
        "latency": dt,
    }


async def test_investigation(client: httpx.AsyncClient) -> dict:
    print("\n========== 3. POLICE INVESTIGATION ==========")
    payload = {
        "case_facts": (
            "Mr. Rajesh Kumar, a Deputy Secretary in the Ministry of Finance, has been "
            "running a private import-export business in his wife's name since January "
            "2025, in violation of service rules. He signed contracts as authorised "
            "signatory and made profits routed to his account."
        ),
        "session_id": f"{SESSION}-inv",
        "user_id": USER_ID,
    }
    t0 = time.perf_counter()
    r = await client.post(f"{API_BASE}/api/investigation", json=payload, timeout=TIMEOUT)
    dt = time.perf_counter() - t0
    print(f"  HTTP {r.status_code}  ({dt:.1f}s)")
    if r.status_code != 200:
        print(f"  body: {r.text[:300]}")
        return {"ok": False, "reason": f"HTTP {r.status_code}"}
    j = r.json()
    report = j.get("report", {})
    summary = report.get("summary", "")
    sections = report.get("applicable_sections", []) or []
    steps = report.get("investigation_steps", []) or []
    risk = report.get("risk_level")
    banned = _check_banned(summary + " " + " ".join(sections), label="investigation")
    has_bns_202 = any("202" in s for s in sections)
    print(f"  summary length: {len(summary)}")
    print(f"  applicable_sections ({len(sections)}): {sections[:5]}")
    print(f"  investigation_steps: {len(steps)}, risk_level: {risk}")
    print(f"  mentions §202 (expected): {has_bns_202}")
    print(f"  banned terms: {banned if banned else '(none — clean)'}")
    print(f"  summary[:300]: {_short(summary, 300)}")
    return {
        "ok": r.status_code == 200 and not banned and bool(sections),
        "banned": banned,
        "sections": sections,
        "has_expected": has_bns_202,
        "latency": dt,
    }


async def test_trial(client: httpx.AsyncClient) -> dict:
    print("\n========== 4. COURTROOM TRIAL ==========")
    payload = {
        "question": (
            "On 20 March 2026 at around 9:30 PM, the accused Mr. Vikram Singh "
            "dishonestly took the complainant Ms. Priya Sharma's mobile phone "
            "(iPhone 15 Pro, worth Rs 1,20,000) from her bag at Khan Market metro "
            "station. CCTV captured the act. The phone was recovered from his bag "
            "at arrest. The complainant identified him at the police station."
        ),
        "court_level": "district",
        "rounds": 1,
        "user_id": USER_ID,
    }
    t0 = time.perf_counter()
    r = await client.post(f"{API_BASE}/api/cases/trial", json=payload, timeout=TIMEOUT)
    dt = time.perf_counter() - t0
    print(f"  HTTP {r.status_code}  ({dt:.1f}s)")
    if r.status_code != 200:
        print(f"  body: {r.text[:300]}")
        return {"ok": False, "reason": f"HTTP {r.status_code}"}
    j = r.json()
    judgment = j.get("judgment", {})
    cites = j.get("citations", []) or []
    cite_pairs = [(c.get("act"), c.get("section_number")) for c in cites]
    final_verdict = judgment.get("final_judgment", "")
    app_sec = judgment.get("applicable_sections", []) or []
    pet = j.get("petitioner", {}).get("opinion", "")
    opp = j.get("opponent", {}).get("opinion", "")
    rebut = j.get("rebuttal", {}).get("opinion", "")
    banned_blob = " ".join([final_verdict, " ".join(app_sec), pet, opp, rebut])
    banned = _check_banned(banned_blob, label="trial")
    has_bns_303 = any(("303" in s) for s in app_sec)
    print(f"  court_level: {j.get('court_level')}")
    print(f"  petitioner: {len(pet)} chars, opponent: {len(opp)} chars, rebuttal: {len(rebut)} chars")
    print(f"  judgment.applicable_sections ({len(app_sec)}): {app_sec[:5]}")
    print(f"  citations ({len(cites)}): {cite_pairs[:5]}")
    print(f"  mentions §303 (expected for theft): {has_bns_303}")
    print(f"  banned terms across all outputs: {banned if banned else '(none — clean)'}")
    print(f"  judgment.final_judgment[:300]: {_short(final_verdict, 300)}")
    return {
        "ok": r.status_code == 200 and not banned and bool(app_sec) and bool(cites),
        "banned": banned,
        "applicable_sections": app_sec,
        "has_expected": has_bns_303,
        "latency": dt,
    }


async def main():
    print(f"Backend: {API_BASE}")
    print(f"Session: {SESSION}")
    async with httpx.AsyncClient() as client:
        results = {
            "assistant":      await test_assistant(client),
            "fir":            await test_fir(client),
            "investigation":  await test_investigation(client),
            "trial":          await test_trial(client),
        }

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for name, r in results.items():
        ok = "✓" if r.get("ok") else "✗"
        latency = r.get("latency", 0)
        banned = r.get("banned") or []
        banned_str = f"  BANNED: {banned}" if banned else ""
        reason = r.get("reason", "")
        print(f"  {ok} {name:14s} ({latency:5.1f}s){banned_str}  {reason}")
    n_pass = sum(1 for r in results.values() if r.get("ok"))
    print(f"\n  Total: {n_pass}/{len(results)} pass")


if __name__ == "__main__":
    asyncio.run(main())
