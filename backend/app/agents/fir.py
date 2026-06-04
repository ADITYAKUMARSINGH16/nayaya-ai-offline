"""FIR drafting agent: gather facts → retrieve sections → draft → persist."""
from __future__ import annotations

from app.core.llm import get_llm
from app.prompts.templates import FIR_DRAFTER
from app.schemas.models import Citation, FIRRequest, FIRResponse
from app.services import db
from app.services.rag import retrieve_context


def _history_text(rows: list[dict]) -> str:
    lines = []
    for r in rows:
        role = "Complainant" if r.get("role") == "user" else "Assistant"
        lines.append(f"{role}: {r.get('message', '')}")
    return "\n".join(lines)


async def run_fir(req: FIRRequest) -> FIRResponse:
    llm = get_llm()

    facts = req.facts or ""
    if not facts:
        try:
            facts = _history_text(db.fetch_history(req.session_id, limit=40))
        except Exception:
            facts = ""
    if not facts.strip():
        facts = "No detailed facts were provided by the complainant."

    rag = await retrieve_context(facts[:1500], top_k=5)

    user_block = (
        f"Complainant Name: {req.complainant_name}\n"
        f"Complainant Address: {req.complainant_address or '[ADDRESS]'}\n"
        f"Complainant Phone: {req.complainant_phone or '[PHONE]'}\n"
        f"Complainant Age: {req.complainant_age or '[AGE]'}\n"
        f"Complainant Gender: {req.complainant_gender or '[GENDER]'}\n"
        f"Police Station: {req.police_station or '[POLICE STATION]'}\n"
        f"Incident Date: {req.incident_date}\n"
        f"Incident Time: {req.incident_time or '[TIME]'}\n"
        f"Incident Location: {req.incident_location or '[LOCATION]'}\n"
        f"Accused: {req.accused or '[ACCUSED NAME]'}\n\n"
        f"Facts / Conversation:\n{facts[:1800]}\n\n"
        f"Relevant Legal Context:\n{rag['context'][:1200]}"
    )

    fir_text = await llm.complete(
        [
            {"role": "system", "content": FIR_DRAFTER},
            {"role": "user", "content": user_block},
        ],
        temperature=0.2,
    )

    record = {}
    try:
        record = db.save_fir(
            {
                "session_id": req.session_id,
                "user_id": req.user_id,
                "complainant_name": req.complainant_name,
                "incident_date": req.incident_date,
                "fir_text": fir_text,
            }
        )
    except Exception:
        pass

    return FIRResponse(
        fir_text=fir_text,
        citations=[Citation(**c) for c in rag["citations"]],
        record_id=record.get("id"),
    )
