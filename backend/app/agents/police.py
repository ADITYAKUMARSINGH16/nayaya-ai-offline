"""Police investigation agent: produce a structured investigation report."""
from __future__ import annotations

from app.core.llm import get_llm
from app.prompts.templates import POLICE_INVESTIGATOR
from app.schemas.models import (
    InvestigationReport,
    InvestigationRequest,
    InvestigationResponse,
)
from app.services import db
from app.services.rag import retrieve_context


async def run_investigation(req: InvestigationRequest) -> InvestigationResponse:
    llm = get_llm()
    rag = await retrieve_context(req.case_facts[:1500], top_k=5)

    data = await llm.complete_json(
        [
            {"role": "system", "content": POLICE_INVESTIGATOR},
            {
                "role": "user",
                "content": (
                    f"CASE FACTS:\n{req.case_facts[:2500]}\n\n"
                    f"LEGAL CONTEXT:\n{rag['context'][:1200]}"
                ),
            },
        ],
        temperature=0.3,
    )

    report = InvestigationReport(**_coerce(data))

    record = {}
    try:
        record = db.save_investigation(
            {
                "fir_id": req.fir_id,
                "session_id": req.session_id,
                "user_id": req.user_id,
                "report": report.model_dump(),
            }
        )
    except Exception:
        pass
    return InvestigationResponse(report=report, record_id=record.get("id"))


def _coerce(data: dict) -> dict:
    """Fill any missing keys with safe defaults so validation never crashes."""
    defaults = {
        "summary": "",
        "investigation_steps": [],
        "evidence": [],
        "witnesses": [],
        "suspects": [],
        "applicable_sections": [],
        "risk_level": "medium",
        "risk_rationale": "",
    }
    return {**defaults, **{k: data.get(k, v) for k, v in defaults.items()}}
