import enum
from sqlalchemy import (
    Column, String, Float, Integer, Boolean, DateTime, Date, ForeignKey, Text, JSON, Enum as SAEnum
)
from sqlalchemy.orm import relationship
from .database import Base


class LeadStatus(str, enum.Enum):
    PENDING_SCORE = "PENDING_SCORE"
    READY_TO_SUBMIT = "READY_TO_SUBMIT"
    HELD = "HELD"
    QA_REVIEW = "QA_REVIEW"


class Speaker(str, enum.Enum):
    AGENT = "AGENT"
    CUSTOMER = "CUSTOMER"
    UNKNOWN = "UNKNOWN"
    OVERLAP = "OVERLAP"


class CheckType(str, enum.Enum):
    SCRIPT = "SCRIPT"
    FACTUAL = "FACTUAL"
    BEHAVIOUR = "BEHAVIOUR"


class ResultType(str, enum.Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    REVIEW = "REVIEW"


class EvaluationMethod(str, enum.Enum):
    DETERMINISTIC = "DETERMINISTIC"
    LLM_SEMANTIC = "LLM_SEMANTIC"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class OverrideAction(str, enum.Enum):
    CONFIRM_FAILURE = "CONFIRM_FAILURE"
    OVERRIDE_TO_PASS = "OVERRIDE_TO_PASS"
    SEND_TO_QA = "SEND_TO_QA"


class Lead(Base):
    __tablename__ = "leads"

    id = Column(String, primary_key=True)
    retailer = Column(String, nullable=False)
    customer_name = Column(String, nullable=False)
    account_holder_name = Column(String, nullable=False)
    email = Column(String, nullable=False)
    address = Column(String, nullable=False)
    plan_id = Column(String, ForeignKey("plans.id"), nullable=False)
    call_date = Column(DateTime, nullable=False)
    status = Column(SAEnum(LeadStatus), default=LeadStatus.PENDING_SCORE, nullable=False)
    agent_name = Column(String, nullable=False)
    audio_path = Column(String, nullable=True)
    # How the lead entered the system: SEEDED (demo data), UPLOADED (transcript
    # uploaded through the UI - the only kind that can be deleted) or INGESTED (API).
    source = Column(String, nullable=False, default="SEEDED", server_default="SEEDED")

    plan = relationship("Plan", back_populates="leads")
    segments = relationship("TranscriptSegment", back_populates="lead", cascade="all, delete-orphan")
    scores = relationship("ScoreResult", back_populates="lead", cascade="all, delete-orphan")
    overrides = relationship("Override", back_populates="lead", cascade="all, delete-orphan")
    human_audits = relationship("HumanAudit", back_populates="lead", cascade="all, delete-orphan")


class Plan(Base):
    __tablename__ = "plans"

    id = Column(String, primary_key=True)
    retailer = Column(String, nullable=False)
    plan_name = Column(String, nullable=False)
    peak_rate_cents = Column(Float, nullable=False)
    off_peak_rate_cents = Column(Float, nullable=False)
    effective_from = Column(Date, nullable=False)
    effective_to = Column(Date, nullable=True)

    leads = relationship("Lead", back_populates="plan")


class TranscriptSegment(Base):
    __tablename__ = "transcript_segments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    lead_id = Column(String, ForeignKey("leads.id"), nullable=False)
    speaker = Column(SAEnum(Speaker), nullable=False)
    start_seconds = Column(Integer, nullable=False)
    end_seconds = Column(Integer, nullable=False)
    text = Column(Text, nullable=False)
    transcription_confidence = Column(Float, nullable=True)

    lead = relationship("Lead", back_populates="segments")


class ChecklistRule(Base):
    __tablename__ = "checklist_rules"

    id = Column(String, primary_key=True)
    retailer = Column(String, nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    check_type = Column(SAEnum(CheckType), nullable=False)
    critical = Column(Boolean, nullable=False, default=False)
    version = Column(String, nullable=False)
    effective_from = Column(Date, nullable=False)
    effective_to = Column(Date, nullable=True)
    matching_config_json = Column(JSON, nullable=False, default=dict)


class ScoreResult(Base):
    __tablename__ = "score_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    lead_id = Column(String, ForeignKey("leads.id"), nullable=False)
    rule_id = Column(String, nullable=False)
    rule_name = Column(String, nullable=False)
    check_type = Column(SAEnum(CheckType), nullable=False)
    result = Column(SAEnum(ResultType), nullable=False)
    critical = Column(Boolean, nullable=False)
    confidence = Column(Float, nullable=False)
    transcript_segment_id = Column(Integer, nullable=True)
    evidence_text = Column(Text, nullable=True)
    timestamp_seconds = Column(Integer, nullable=True)
    expected_value = Column(String, nullable=True)
    actual_value = Column(String, nullable=True)
    reason = Column(Text, nullable=False)
    rule_version = Column(String, nullable=False)
    evaluation_method = Column(SAEnum(EvaluationMethod), nullable=False)

    lead = relationship("Lead", back_populates="scores")


class Override(Base):
    __tablename__ = "overrides"

    id = Column(Integer, primary_key=True, autoincrement=True)
    lead_id = Column(String, ForeignKey("leads.id"), nullable=False)
    reviewer_name = Column(String, nullable=False)
    action = Column(SAEnum(OverrideAction), nullable=False)
    reason = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False)

    lead = relationship("Lead", back_populates="overrides")


class HumanAudit(Base):
    __tablename__ = "human_audits"

    id = Column(Integer, primary_key=True, autoincrement=True)
    lead_id = Column(String, ForeignKey("leads.id"), nullable=False)
    rule_id = Column(String, nullable=False)
    auditor_result = Column(SAEnum(ResultType), nullable=False)
    auditor_note = Column(Text, nullable=True)
    reviewed_at = Column(DateTime, nullable=False)

    lead = relationship("Lead", back_populates="human_audits")
