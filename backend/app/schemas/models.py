"""Pydantic request/response schemas — the shared data contract."""
from __future__ import annotations

from pydantic import BaseModel, Field


# ---- shared -------------------------------------------------------------

class Citation(BaseModel):
    act: str = ""
    section_number: str = ""
    section_title: str = ""
    score: float | None = None
    snippet: str = ""
    verified: bool | None = None
    verify_note: str | None = None


# ---- assistant ----------------------------------------------------------

class AssistantRequest(BaseModel):
    chat_input: str = Field(..., alias="chatInput")
    session_id: str = Field(..., alias="sessionId")
    user_id: str | None = Field(default=None, alias="userId")

    model_config = {"populate_by_name": True}


class AssistantResponse(BaseModel):
    content: str
    intent: str
    citations: list[Citation] = []
    low_confidence: bool = False


# ---- FIR ----------------------------------------------------------------

class FIRRequest(BaseModel):
    session_id: str = Field(..., alias="sessionId")
    user_id: str | None = Field(default=None, alias="userId")
    complainant_name: str = Field(..., alias="complainantName")
    complainant_address: str | None = Field(default=None, alias="complainantAddress")
    complainant_phone: str | None = Field(default=None, alias="complainantPhone")
    complainant_age: str | None = Field(default=None, alias="complainantAge")
    complainant_gender: str | None = Field(default=None, alias="complainantGender")
    police_station: str | None = Field(default=None, alias="policeStation")
    incident_date: str = Field(..., alias="incidentDate")
    incident_time: str | None = Field(default=None, alias="incidentTime")
    incident_location: str | None = Field(default=None, alias="incidentLocation")
    accused: str | None = None
    facts: str | None = None  # optional free text if no chat history

    model_config = {"populate_by_name": True}


class FIRResponse(BaseModel):
    fir_text: str
    citations: list[Citation] = []
    record_id: str | None = None


# ---- police investigation ----------------------------------------------

class InvestigationRequest(BaseModel):
    case_facts: str = Field(..., alias="caseFacts")
    fir_id: str | None = Field(default=None, alias="firId")
    session_id: str | None = Field(default=None, alias="sessionId")
    user_id: str | None = Field(default=None, alias="userId")

    model_config = {"populate_by_name": True}


class InvestigationReport(BaseModel):
    summary: str
    investigation_steps: list[str] = []
    evidence: list[str] = []
    witnesses: list[str] = []
    suspects: list[str] = []
    applicable_sections: list[str] = []
    risk_level: str = "medium"
    risk_rationale: str = ""


class InvestigationResponse(BaseModel):
    report: InvestigationReport
    record_id: str | None = None


# ---- courtroom ----------------------------------------------------------

class TrialRequest(BaseModel):
    question: str  # full case facts (FIR + investigation summary)
    case_id: str | None = Field(default=None, alias="caseId")
    user_id: str | None = Field(default=None, alias="userId")
    rounds: int = 1
    court_level: str = "district"  # district | high | supreme

    model_config = {"populate_by_name": True}


class LawyerArgument(BaseModel):
    opinion: str = ""
    arguments: list[str] = []


class Judgment(BaseModel):
    court_observations: list[str] = []
    facts_established: list[str] = []
    disputed_facts: list[str] = []
    evidence_evaluation: list[str] = []
    applicable_sections: list[str] = []
    procedural_findings: list[str] = []
    final_judgment: str = ""
    liability_assessment: str = ""
    recommended_next_steps: list[str] = []


class TrialResponse(BaseModel):
    success: bool = True
    court_level: str
    petitioner: LawyerArgument
    opponent: LawyerArgument
    rebuttal: LawyerArgument
    cross_examination: LawyerArgument | None = None
    judgment: Judgment
    citations: list[Citation] = []
    case_id: str | None = None


# ---- lawyer analysis ----------------------------------------------------

class LawyerAnalysisResponse(BaseModel):
    strategy: str
    strengths: list[str] = []
    weaknesses: list[str] = []
    evidence_needed: list[str] = []
    citations: list[Citation] = []
    session_id: str | None = None


# ---- judge analysis -----------------------------------------------------

class SimilarCase(BaseModel):
    title: str = ""
    court: str = ""
    year: str = ""
    disposition: str = ""
    snippet: str = ""
    text: str = ""
    score: float | None = None

class JudgeAnalysisResponse(BaseModel):
    legal_questions: list[str] = []
    admissibility_issues: list[str] = []
    potential_liabilities: list[str] = []
    citations: list[Citation] = []
    similar_cases: list[SimilarCase] = []
    session_id: str | None = None
