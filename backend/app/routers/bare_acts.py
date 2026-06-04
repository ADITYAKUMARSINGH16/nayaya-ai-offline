from typing import Any, List, Optional
from fastapi import APIRouter, Query, HTTPException

from app.services import section_lookup

router = APIRouter(prefix="/bare-acts", tags=["Bare Acts"])

@router.get("/", response_model=List[str])
async def list_acts():
    """Returns a list of available bare acts."""
    acts = section_lookup.get_all_acts()
    if not acts:
        raise HTTPException(status_code=404, detail="No acts found in the database.")
    return acts

@router.get("/search", response_model=List[dict[str, Any]])
async def search_bare_acts(
    q: str = Query(..., min_length=1, description="Search query"),
    act: Optional[str] = Query(None, description="Filter by a specific act")
):
    """Simple text search across bare acts."""
    acts_filter = [act] if act else None
    results = section_lookup.search_sections(q, acts=acts_filter)
    return results

@router.get("/{act}", response_model=List[dict[str, Any]])
async def get_act(act: str):
    """Returns all sections for a given act."""
    sections = section_lookup.get_sections_by_act(act)
    if not sections:
        raise HTTPException(status_code=404, detail=f"No sections found for act: {act}")
    return sections
