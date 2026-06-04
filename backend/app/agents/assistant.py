"""The legal-assistant chatbot agent.

Flow (v3 with query planner):
  1. Save user msg + load chat history
  2. Cheap CLASSIFIER LLM call gates non-legal queries (saves planner cost
     on "hi", "thanks", etc.)
  3. For LEGAL queries: hand off to query_planner.execute_plan, which runs
     plan → execute → reflect → synthesize and returns a composed answer
     with citations + provenance.

The planner subsumes the old direct retrieve_context + ASSISTANT-prompt
sequence. It produces a richer answer (multi-sub-query, coreference-resolved,
retry-on-failure) and ties each part back to citations.

FIR / police / courtroom agents continue to call retrieve_context directly —
they have well-defined output schemas and don't need the planner's overhead.
"""
from __future__ import annotations

from app.core.llm import get_llm
from app.prompts.templates import CLASSIFIER
from app.schemas.models import AssistantResponse, Citation
from app.services import db
from app.services.query_planner import execute_plan_safe

GREETING_REPLY = (
    "Hello! I am Nyaya Sahayak, your legal assistant for Indian law "
    "(BNS, BNSS, BSA 2023). Ask me about a section, an offence, punishment, "
    "or what to do in a situation."
)
NON_LEGAL_REPLY = (
    "I can only help with Indian legal matters (BNS, BNSS, BSA 2023). "
    "Please ask a law-related question."
)


def _format_history(rows: list[dict]) -> str:
    """Plain-text history (for the classifier prompt)."""
    lines: list[str] = []
    last = None
    for r in rows:
        role = "Assistant" if r.get("role") == "assistant" else "User"
        msg = (r.get("message") or "").replace("\n", " ").strip()
        if msg and msg != last:
            lines.append(f"{role}: {msg}")
            last = msg
    return "\n".join(lines)


async def run_assistant(
    *, chat_input: str, session_id: str, user_id: str | None
) -> AssistantResponse:
    llm = get_llm()

    # Persist the user's message + load recent history
    try:
        db.save_message(session_id, user_id, "user", chat_input)
    except Exception:
        pass
    history_rows = db.fetch_history(session_id, limit=12)
    history_text = _format_history(history_rows)

    # Cheap classifier gate — block non-legal queries before paying planner cost
    intent = (
        await llm.complete(
            [
                {"role": "system", "content": CLASSIFIER},
                {"role": "user", "content": f"Conversation:\n{history_text}\n\nCurrent: {chat_input}"},
            ],
            fast=True,
            max_tokens=5,
            temperature=0.0,
        )
    ).strip().upper()

    if "LEGAL" not in intent:
        reply = GREETING_REPLY if "GREET" in intent else NON_LEGAL_REPLY
        try:
            db.save_message(session_id, user_id, "assistant", reply)
        except Exception:
            pass
        return AssistantResponse(content=reply, intent=intent or "NON_LEGAL")

    # Legal query → run the full planner pipeline
    plan_result = await execute_plan_safe(chat_input, history=history_rows, top_k_per_subquery=5)

    try:
        db.save_message(session_id, user_id, "assistant", plan_result.answer)
    except Exception:
        pass

    return AssistantResponse(
        content=plan_result.answer,
        intent="LEGAL",
        citations=[Citation(**c) for c in plan_result.citations],
        low_confidence=plan_result.low_confidence,
    )
