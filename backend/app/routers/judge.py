from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.security import CurrentUser, require_judge
from app.schemas import models
from app.services import db

router = APIRouter(prefix="/judge", tags=["judge"])


@router.post("/analyze", response_model=models.JudgeAnalysisResponse)
async def analyze_case(
    req: models.InvestigationRequest,
    user: Annotated[CurrentUser, Depends(require_judge)],
):
    """Judge preliminary case analysis."""
    from app.services.rag import retrieve_context
    from app.agents.verifier import verify_text
    from app.core.llm import get_llm
    from app.prompts.templates import JUDGE_ANALYSIS
    import uuid
    import json

    # 1. Retrieve statutory context
    rag = await retrieve_context(req.case_facts, top_k=6, intent_hint="APPLY_FACTS")
    ctx = rag["context"]

    # 1b. Retrieve historical case laws
    from app.services.vector_store import search_case_laws
    similar_cases_data = await search_case_laws(req.case_facts, top_k=3)
    
    cases_context = "NO HISTORICAL PRECEDENTS FOUND."
    if similar_cases_data:
        cases_context = "\n\n".join(
            f"Case: {c['title']} ({c['year']}) - {c['court']}\nDisposition: {c['disposition']}\nSummary: {c['snippet']}"
            for c in similar_cases_data
        )

    # 2. Complete with LLM
    data = await get_llm().complete_json(
        [
            {"role": "system", "content": JUDGE_ANALYSIS},
            {"role": "user", "content": f"CASE FACTS:\n{req.case_facts}\n\nSTATUTORY LAW:\n{ctx}\n\nPRECEDENT CASES:\n{cases_context}"},
        ],
        temperature=0.2,
    )
    
    # 3. Verify citations
    blob = " ".join(data.get("legal_questions", []) + data.get("admissibility_issues", []) + data.get("potential_liabilities", []))
    citations = await verify_text(blob)
    
    session_id = f"judge_{uuid.uuid4().hex}"
    try:
        db.save_message(session_id, user.id, "user", req.case_facts, {"type": "judge_analysis"})
        db.save_message(session_id, user.id, "assistant", json.dumps(data), {"type": "judge_analysis"})
    except Exception:
        pass

    return models.JudgeAnalysisResponse(
        legal_questions=data.get("legal_questions", []),
        admissibility_issues=data.get("admissibility_issues", []),
        potential_liabilities=data.get("potential_liabilities", []),
        citations=citations,
        similar_cases=similar_cases_data,
        session_id=session_id,
    )


class VerdictOverrideRequest(BaseModel):
    verdict: dict[str, Any]
    status: str  # approved, rejected, modified


@router.get("/cases")
async def get_judge_cases(
    user: Annotated[CurrentUser, Depends(require_judge)],
):
    """Get all cases for the judge dashboard."""
    cases = db.list_all_cases()
    return cases


@router.post("/cases/{case_id}/claim")
async def claim_case(
    case_id: str,
    user: Annotated[CurrentUser, Depends(require_judge)],
):
    """Assign case to the current judge."""
    updated = db.assign_case(case_id, "judge", user.id)
    return updated


@router.post("/cases/{case_id}/verdict")
async def submit_verdict(
    case_id: str,
    req: VerdictOverrideRequest,
    user: Annotated[CurrentUser, Depends(require_judge)],
):
    """Approve or override the AI verdict."""
    case = db.get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
        
    updated = db.submit_human_verdict(case_id, req.verdict, req.status)
    return updated


@router.get("/cases/{case_id}/similar", response_model=list[models.SimilarCase])
async def get_similar_cases(
    case_id: str,
    user: Annotated[CurrentUser, Depends(require_judge)],
):
    """Get similar cases for a pending verdict case."""
    from app.services.vector_store import search_case_laws
    
    case = db.get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
        
    facts = case.get("question", "")
    if not facts:
        return []
        
    similar_cases_data = await search_case_laws(facts, top_k=3)
    return similar_cases_data


@router.get("/case-laws/search", response_model=list[models.SimilarCase])
async def search_supreme_court_cases(
    q: str,
    user: Annotated[CurrentUser, Depends(require_judge)],
):
    """Search historical Supreme Court case laws."""
    from app.services.vector_store import search_case_laws
    
    if not q.strip():
        # Return default recent cases to populate Table of Contents
        results = await search_case_laws("", top_k=20)
        return results
        
    results = await search_case_laws(q, top_k=20)
    return results
