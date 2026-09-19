from datetime import date, datetime
from typing import Optional, List
from pydantic import BaseModel, ConfigDict


# ---------- Plan ----------

class PlanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    retailer: str
    plan_name: str
    peak_rate_cents: float
    off_peak_rate_cents: float
    effective_from: date
    effective_to: Optional[date] = None


# ---------- Transcript ----------

class TranscriptSegmentIn(BaseModel):
    speaker: str
    start_seconds: int
    end_seconds: int
    text: str
    transcription_confidence: Optional[float] = None


class TranscriptSegmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    speaker: str
    start_seconds: int
    end_seconds: int
    text: str
    transcription_confidence: Optional[float] = None


# ---------- Lead ----------

class LeadIngestIn(BaseModel):
    id: str
    retailer: str
    customer_name: str
    account_holder_name: str
    email: str
    address: str
    plan_id: str
    call_date: datetime
    agent_name: str
    audio_path: Optional[str] = None
    segments: List[TranscriptSegmentIn] = []


class LeadOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    retailer: str
    customer_name: str
    account_holder_name: str
    email: str
    address: str
    plan_id: str
    call_date: datetime
    status: str
    agent_name: str
    audio_path: Optional[str] = None
    source: str = "SEEDED"


class LeadDetailOut(LeadOut):
    plan: Optional[PlanOut] = None
    segments: List[TranscriptSegmentOut] = []


class LeadSummaryOut(LeadOut):
    checklist_total: int = 0
    checklist_scored: int = 0
    critical_fail_count: int = 0


# ---------- Score results ----------

class ScoreResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    lead_id: str
    rule_id: str
    rule_name: str
    check_type: str
    result: str
    critical: bool
    confidence: float
    transcript_segment_id: Optional[int] = None
    evidence_text: Optional[str] = None
    timestamp_seconds: Optional[int] = None
    expected_value: Optional[str] = None
    actual_value: Optional[str] = None
    reason: str
    rule_version: str
    evaluation_method: str


class ScoreSaleResponse(BaseModel):
    lead_id: str
    status: str
    results: List[ScoreResultOut]


class ScoreAllItem(BaseModel):
    lead_id: str
    status: Optional[str] = None
    error: Optional[str] = None


class ScoreAllResponse(BaseModel):
    total: int
    scored: int
    failed: int
    results: List[ScoreAllItem]


# ---------- Overrides ----------

class OverrideIn(BaseModel):
    reviewer_name: str
    action: str
    reason: str


class OverrideOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    lead_id: str
    reviewer_name: str
    action: str
    reason: str
    created_at: datetime


# ---------- Dashboard ----------

class DashboardSummary(BaseModel):
    total_sales: int
    ready_to_submit: int
    held: int
    qa_review: int
    pending_score: int
    critical_failure_rate: float
    checklist_coverage: float
    human_auditor_agreement_rate: float
    critical_false_pass_count: int
    recent_leads: List[LeadSummaryOut]


# ---------- Evaluation ----------

class ConfusionCell(BaseModel):
    automated: str
    human: str
    count: int


class EvaluationMetrics(BaseModel):
    total_audited_checks: int
    overall_agreement_rate: float
    critical_agreement_rate: float
    critical_false_pass_count: int
    critical_false_fail_count: int
    confusion_matrix: List[ConfusionCell]
