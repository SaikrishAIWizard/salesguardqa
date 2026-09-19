from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..services import lead_service, transcript_service, rule_service, transcript_upload_service
from ..services.scoring_service import score_lead, ScoringError

router = APIRouter(tags=["leads"])

MAX_UPLOAD_BYTES = 1_000_000


def build_lead_summary(db: Session, lead: models.Lead) -> schemas.LeadSummaryOut:
    rules = rule_service.get_active_rules(db, lead.retailer, lead.call_date.date())
    scores = db.query(models.ScoreResult).filter(models.ScoreResult.lead_id == lead.id).all()
    critical_fail_count = sum(1 for s in scores if s.critical and s.result == models.ResultType.FAIL)
    return schemas.LeadSummaryOut(
        **schemas.LeadOut.model_validate(lead).model_dump(),
        checklist_total=len(rules),
        checklist_scored=len(scores),
        critical_fail_count=critical_fail_count,
    )


@router.get("/leads", response_model=list[schemas.LeadSummaryOut])
def list_leads(db: Session = Depends(get_db)):
    leads = lead_service.list_leads(db)
    return [build_lead_summary(db, lead) for lead in leads]


@router.get("/leads/{lead_id}", response_model=schemas.LeadDetailOut)
def get_lead(lead_id: str, db: Session = Depends(get_db)):
    lead = lead_service.get_lead(db, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    segments = transcript_service.get_segments(db, lead_id)
    redacted_segments = transcript_service.to_redacted_schema(segments)
    detail = schemas.LeadDetailOut(
        **schemas.LeadOut.model_validate(lead).model_dump(),
        plan=schemas.PlanOut.model_validate(lead.plan) if lead.plan else None,
        segments=redacted_segments,
    )
    return detail


@router.post("/calls/ingest", response_model=schemas.LeadOut)
def ingest_call(payload: schemas.LeadIngestIn, db: Session = Depends(get_db)):
    lead = lead_service.ingest_call(db, payload)
    return lead


@router.post("/leads/upload", response_model=schemas.LeadOut, status_code=201)
async def upload_lead(
    file: UploadFile = File(...),
    lead_id: Optional[str] = Form(None),
    retailer: Optional[str] = Form(None),
    customer_name: Optional[str] = Form(None),
    account_holder_name: Optional[str] = Form(None),
    email: Optional[str] = Form(None),
    address: Optional[str] = Form(None),
    plan_id: Optional[str] = Form(None),
    agent_name: Optional[str] = Form(None),
    call_date: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """Creates a new lead from an uploaded transcript file and scores it immediately."""
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Transcript file is too large (max 1 MB).")

    try:
        payload = transcript_upload_service.build_ingest_payload(
            file.filename or "",
            content,
            dict(
                lead_id=lead_id, retailer=retailer, customer_name=customer_name,
                account_holder_name=account_holder_name, email=email, address=address,
                plan_id=plan_id, agent_name=agent_name, call_date=call_date,
            ),
        )
    except transcript_upload_service.TranscriptParseError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    # Unlike /calls/ingest (which re-ingests), an upload must never overwrite a lead.
    if lead_service.get_lead(db, payload.id) is not None:
        raise HTTPException(status_code=409, detail=f"Lead '{payload.id}' already exists. Use a different lead ID.")
    if db.query(models.Plan).filter(models.Plan.id == payload.plan_id).first() is None:
        raise HTTPException(status_code=422, detail=f"Unknown plan_id '{payload.plan_id}'.")

    lead = lead_service.ingest_call(db, payload, source="UPLOADED")
    try:
        score_lead(db, lead)
    except ScoringError as exc:
        raise HTTPException(status_code=400, detail=f"Lead saved but could not be scored: {exc}")
    db.refresh(lead)
    return lead


@router.delete("/leads/{lead_id}", status_code=204)
def delete_lead(lead_id: str, db: Session = Depends(get_db)):
    """Deletes a lead that was uploaded manually. Seeded/ingested leads are protected."""
    lead = lead_service.get_lead(db, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    if lead.source != "UPLOADED":
        raise HTTPException(status_code=403, detail="Only leads uploaded manually can be deleted.")
    lead_service.delete_lead(db, lead)


@router.post("/leads/{lead_id}/override", response_model=schemas.OverrideOut)
def create_override(lead_id: str, payload: schemas.OverrideIn, db: Session = Depends(get_db)):
    lead = lead_service.get_lead(db, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    if not payload.reason or not payload.reason.strip():
        raise HTTPException(status_code=422, detail="A reason is required for every human review action.")

    try:
        action = models.OverrideAction(payload.action)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid action '{payload.action}'")

    override = models.Override(
        lead_id=lead_id,
        reviewer_name=payload.reviewer_name,
        action=action,
        reason=payload.reason,
        created_at=datetime.now(timezone.utc),
    )
    db.add(override)

    # The override is logged permanently; it also updates lead status so the
    # decision is reflected in the dashboard. It never rewrites automated
    # score_results - those remain as the system's original evidence trail.
    if action == models.OverrideAction.OVERRIDE_TO_PASS:
        lead.status = models.LeadStatus.READY_TO_SUBMIT
    elif action == models.OverrideAction.CONFIRM_FAILURE:
        lead.status = models.LeadStatus.HELD
    elif action == models.OverrideAction.SEND_TO_QA:
        lead.status = models.LeadStatus.QA_REVIEW

    db.commit()
    db.refresh(override)
    return override


@router.get("/leads/{lead_id}/overrides", response_model=list[schemas.OverrideOut])
def list_overrides(lead_id: str, db: Session = Depends(get_db)):
    lead = lead_service.get_lead(db, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    return (
        db.query(models.Override)
        .filter(models.Override.lead_id == lead_id)
        .order_by(models.Override.created_at)
        .all()
    )
