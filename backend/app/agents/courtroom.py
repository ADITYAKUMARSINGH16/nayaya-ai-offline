"""Courtroom simulation agent.

Pipeline: legal retrieval → petitioner → opposing → rebuttal (xN rounds) → judge.
The judge's cited sections are then run through the verifier so the verdict ships
with trust signals instead of unchecked citations.
"""
from __future__ import annotations

from app.agents.verifier import verify_text
from app.core.llm import get_llm
from app.prompts.templates import JUDGE, OPPOSING, PETITIONER, REBUTTAL, CROSS_EXAMINATION
from app.schemas.models import (
    Judgment,
    LawyerArgument,
    TrialRequest,
    TrialResponse,
)
from app.services import db
from app.services.n8n import notify_verdict
from app.services.rag import retrieve_context

_APPEAL_NOTE = {
    "district": "This is a court of first instance.",
    "high": "This is a High Court appeal — review the lower court's findings for errors of law and fact.",
    "supreme": "This is a Supreme Court appeal — focus on substantial questions of law and constitutional issues.",
}


async def _argue(system: str, user: str) -> LawyerArgument:
    data = await get_llm().complete_json(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.3,
    )
    return LawyerArgument(
        opinion=str(data.get("opinion", "")),
        arguments=[str(a) for a in data.get("arguments", [])],
    )


async def run_trial(req: TrialRequest) -> TrialResponse:
    # No truncation on case facts — they are central to element-matching for
    # the trial. Bumped top_k=10 (was 6) so the judge has a broader candidate
    # pool. intent_hint=APPLY_FACTS triggers rag.py's element-matcher pass
    # which drops sections whose elements the facts don't satisfy (e.g. drops
    # §316 Breach of Trust for a theft-from-bag case because no entrustment).
    rag = await retrieve_context(req.question, top_k=10, intent_hint="APPLY_FACTS")
    ctx = rag["context"]
    appeal = _APPEAL_NOTE.get(req.court_level, _APPEAL_NOTE["district"])

    petitioner = await _argue(
        PETITIONER, f"{appeal}\n\nCASE:\n{req.question}\n\nLEGAL CONTEXT:\n{ctx}"
    )

    opponent = LawyerArgument()
    rebuttal = LawyerArgument()
    cross_examination = LawyerArgument()
    rounds = max(1, min(req.rounds, 3))
    for _ in range(rounds):
        opponent = await _argue(
            OPPOSING,
            f"CASE:\n{req.question}\n\n"
            f"PETITIONER OPINION:\n{petitioner.opinion}\n"
            f"PETITIONER ARGUMENTS:\n{petitioner.arguments}\n\nLEGAL CONTEXT:\n{ctx}",
        )
        cross_examination = await _argue(
            CROSS_EXAMINATION,
            f"CASE:\n{req.question}\n\n"
            f"PETITIONER:\n{petitioner.opinion}\n{petitioner.arguments}\n\n"
            f"DEFENCE:\n{opponent.opinion}\n{opponent.arguments}\n\nLEGAL CONTEXT:\n{ctx}",
        )
        rebuttal = await _argue(
            REBUTTAL,
            f"CASE:\n{req.question}\n\n"
            f"PETITIONER:\n{petitioner.opinion}\n{petitioner.arguments}\n\n"
            f"DEFENCE:\n{opponent.opinion}\n{opponent.arguments}\n\n"
            f"CROSS EXAMINATION:\n{cross_examination.opinion}\n{cross_examination.arguments}\n\n"
            f"LEGAL CONTEXT:\n{ctx}",
        )

    judge_data = await get_llm().complete_json(
        [
            {"role": "system", "content": JUDGE},
            {
                "role": "user",
                "content": (
                    f"{appeal}\n\n"
                    f"CASE FACTS:\n{req.question}\n\n"
                    f"PETITIONER:\n{petitioner.model_dump()}\n\n"
                    f"DEFENCE:\n{opponent.model_dump()}\n\n"
                    f"CROSS EXAMINATION:\n{cross_examination.model_dump()}\n\n"
                    f"REBUTTAL:\n{rebuttal.model_dump()}\n\n"
                    f"LEGAL CONTEXT:\n{ctx}"
                ),
            },
        ],
        temperature=0.3,
    )
    judgment = Judgment(**_coerce_judgment(judge_data))

    cited_blob = " ".join(judgment.applicable_sections) + " " + judgment.final_judgment
    citations = await verify_text(cited_blob)

    case_id = req.case_id
    # Keep `cases.judgement_output` as a "latest verdict" pointer (backwards
    # compat for the dashboard), but every level's full verdict survives in
    # the new `judgments` table so appeals don't overwrite history.
    payload = {
        "question": req.question,
        "court_level": req.court_level,
        "lawyer_output": petitioner.model_dump(),
        "opponent_output": opponent.model_dump(),
        "rebuttal_output": rebuttal.model_dump(),
        "judgement_output": judgment.model_dump(),
        "status": "awaiting_verdict",
    }
    try:
        if case_id:
            db.update_case(case_id, payload)
        else:
            created = db.create_case({**payload, "user_id": req.user_id})
            case_id = created.get("id")
    except Exception:
        pass

    # Persist this court level's verdict in the appeal-chain table (upsert
    # on (case_id, court_level) so re-running a trial at the same level
    # replaces rather than duplicates).
    try:
        if case_id:
            db.upsert_judgment({
                "case_id":           case_id,
                "user_id":           req.user_id,
                "court_level":       req.court_level,
                "petitioner_output": petitioner.model_dump(),
                "opponent_output":   opponent.model_dump(),
                "rebuttal_output":   rebuttal.model_dump(),
                "judgment":          judgment.model_dump(),
                "citations":         [c.model_dump() for c in citations],
            })
            
            # Save to chat history
            import json
            session_id = f"trial_{case_id}"
            db.save_message(session_id, req.user_id, "user", req.question, {"type": "trial"})
            trial_data = {
                "court_level": req.court_level,
                "petitioner": petitioner.model_dump(),
                "opponent": opponent.model_dump(),
                "rebuttal": rebuttal.model_dump(),
                "cross_examination": cross_examination.model_dump(),
                "judgment": judgment.model_dump(),
            }
            db.save_message(session_id, req.user_id, "assistant", json.dumps(trial_data), {"type": "trial"})
    except Exception:
        pass

    # Fire-and-forget verdict notification (Email/Slack/Telegram via n8n).
    # Lives HERE (in the agent) rather than in the cases.py router so that
    # any caller of run_trial — the trial endpoint, the agent-petitioner
    # workflow, tests, future internal callers — all trigger notifications
    # automatically. Caller passes user_email through TrialRequest so the
    # email channel knows where to address the reply. Wrapped in try/except
    # so n8n outages never fail trials.
    try:
        await notify_verdict({
            "case_id":             case_id,
            "court_level":         req.court_level,
            "final_judgment":      judgment.final_judgment,
            "applicable_sections": judgment.applicable_sections,
            "user_email":          req.user_email,
        })
    except Exception:
        pass

    return TrialResponse(
        court_level=req.court_level,
        petitioner=petitioner,
        opponent=opponent,
        rebuttal=rebuttal,
        cross_examination=cross_examination,
        judgment=judgment,
        citations=citations,
        case_id=case_id,
    )


def _coerce_judgment(data: dict) -> dict:
    defaults = {
        "court_observations": [],
        "facts_established": [],
        "disputed_facts": [],
        "evidence_evaluation": [],
        "applicable_sections": [],
        "procedural_findings": [],
        "final_judgment": "",
        "liability_assessment": "",
        "recommended_next_steps": [],
    }
    return {**defaults, **{k: data.get(k, v) for k, v in defaults.items()}}
