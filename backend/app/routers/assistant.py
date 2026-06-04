"""Assistant routes — non-streaming (JSON) + streaming (SSE)."""
from __future__ import annotations

import asyncio
import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sse_starlette.sse import EventSourceResponse

from app.agents.assistant import (
    GREETING_REPLY,
    NON_LEGAL_REPLY,
    _format_history,
)
from app.agents.assistant import run_assistant
from app.core.llm import get_llm
from app.core.security import CurrentUser, get_current_user
from app.prompts.templates import ASSISTANT, CLASSIFIER
from app.schemas.models import AssistantRequest, AssistantResponse, Citation
from app.services import db
from app.services.rag import retrieve_context

router = APIRouter(prefix="/assistant", tags=["assistant"])


@router.post("", response_model=AssistantResponse)
async def assistant(
    req: AssistantRequest,
    user: Annotated[CurrentUser, Depends(get_current_user)],
):
    try:
        return await run_assistant(
            chat_input=req.chat_input,
            session_id=req.session_id,
            user_id=user.id or req.user_id,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Assistant failed: {exc}")


@router.post("/stream")
async def assistant_stream(
    req: AssistantRequest,
    user: Annotated[CurrentUser, Depends(get_current_user)],
):
    """SSE stream: emits `intent`, then `token`s, then `citations`, then `done`."""

    async def gen():
        llm = get_llm()
        user_id = user.id or req.user_id

        try:
            db.save_message(req.session_id, user_id, "user", req.chat_input)
        except Exception:
            pass
        history = _format_history(db.fetch_history(req.session_id, limit=12))

        # 1) classify
        intent_raw = await llm.complete(
            [
                {"role": "system", "content": CLASSIFIER},
                {"role": "user", "content": f"Conversation:\n{history}\n\nCurrent: {req.chat_input}"},
            ],
            fast=True,
            max_tokens=5,
            temperature=0.0,
        )
        intent = intent_raw.strip().upper()
        yield {"event": "intent", "data": intent}

        if "LEGAL" not in intent:
            reply = GREETING_REPLY if "GREET" in intent else NON_LEGAL_REPLY
            try:
                db.save_message(
                    req.session_id, user_id, "assistant", reply,
                    metadata={"intent": intent, "citations": [], "low_confidence": False},
                )
            except Exception:
                pass
            yield {"event": "token", "data": reply}
            yield {"event": "done", "data": json.dumps({"intent": intent})}
            return

        # 2) retrieve — top_k=4 so the citations panel stays focused on the
        # truly relevant sections after LLM reranking.
        rag = await retrieve_context(req.chat_input, top_k=4)
        citation_payload = [Citation(**c).model_dump() for c in rag["citations"]]
        yield {"event": "citations", "data": json.dumps(citation_payload)}

        # 3) stream the answer
        collected: list[str] = []
        try:
            async for chunk in llm.stream(
                [
                    {"role": "system", "content": ASSISTANT},
                    {
                        "role": "user",
                        "content": (
                            f"Conversation History:\n{history}\n\n"
                            f"Current Question:\n{req.chat_input}\n\n"
                            f"Legal Context:\n{rag['context'] or 'No relevant sections found.'}"
                        ),
                    },
                ],
                temperature=0.3,
            ):
                collected.append(chunk)
                yield {"event": "token", "data": chunk}
                await asyncio.sleep(0)  # cooperative
        except Exception as exc:
            yield {"event": "error", "data": str(exc)}
            return

        full = "".join(collected)
        try:
            db.save_message(
                req.session_id, user_id, "assistant", full,
                metadata={
                    "intent": "LEGAL",
                    "citations": citation_payload,
                    "low_confidence": rag["low_confidence"],
                },
            )
        except Exception:
            pass

        yield {
            "event": "done",
            "data": json.dumps({"intent": "LEGAL", "low_confidence": rag["low_confidence"]}),
        }

    return EventSourceResponse(gen())
