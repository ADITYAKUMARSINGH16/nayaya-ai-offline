from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.llm import get_llm
from app.core.security import CurrentUser, require_lawyer
from app.prompts.templates import LAWYER_ANALYSIS
from app.schemas.models import LawyerAnalysisResponse
from app.services import db
from app.services.rag import retrieve_context
from app.agents.verifier import verify_text
import uuid
import json

router = APIRouter(prefix="/lawyer", tags=["lawyer"])


class LawyerAnalyzeRequest(BaseModel):
    case_facts: str = Field(..., alias="caseFacts")
    case_id: str | None = Field(default=None, alias="caseId")


@router.get("/cases")
async def get_lawyer_cases(
    user: Annotated[CurrentUser, Depends(require_lawyer)],
):
    """Get cases. Can be filtered by assigned_lawyer later."""
    cases = db.list_all_cases()
    return cases


@router.post("/cases/{case_id}/claim")
async def claim_case(
    case_id: str,
    user: Annotated[CurrentUser, Depends(require_lawyer)],
):
    """Assign case to the current lawyer."""
    updated = db.assign_case(case_id, "lawyer", user.id)
    return updated


@router.post("/analyze", response_model=LawyerAnalysisResponse)
async def analyze_case(
    req: LawyerAnalyzeRequest,
    user: Annotated[CurrentUser, Depends(require_lawyer)],
):
    """Generate strategic analysis, strengths, weaknesses for a case."""
    try:
        rag = await retrieve_context(req.case_facts, top_k=5)
        ctx = rag["context"]

        prompt = f"CASE FACTS:\n{req.case_facts}\n\nLEGAL CONTEXT:\n{ctx}"
        
        data = await get_llm().complete_json(
            [{"role": "system", "content": LAWYER_ANALYSIS}, {"role": "user", "content": prompt}],
            temperature=0.3,
        )
        
        # 3. Verify citations
        blob = " ".join(data.get("strengths", []) + data.get("weaknesses", []))
        citations = await verify_text(blob)
        
        session_id = f"lawyer_{uuid.uuid4().hex}"
        try:
            db.save_message(session_id, user.id, "user", req.case_facts, {"type": "lawyer_analysis"})
            db.save_message(session_id, user.id, "assistant", json.dumps(data), {"type": "lawyer_analysis"})
        except Exception:
            pass

        return LawyerAnalysisResponse(
            strategy=data.get("strategy", ""),
            strengths=data.get("strengths", []),
            weaknesses=data.get("weaknesses", []),
            evidence_needed=data.get("evidence_needed", []),
            citations=citations,
            session_id=session_id,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Lawyer analysis failed: {exc}")
