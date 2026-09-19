from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..services import lead_service, rule_service, evaluation_service
from .leads import build_lead_summary

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard/summary", response_model=schemas.DashboardSummary)
def dashboard_summary(db: Session = Depends(get_db)):
    leads = lead_service.list_leads(db)

    total = len(leads)
    ready = sum(1 for l in leads if l.status == models.LeadStatus.READY_TO_SUBMIT)
    held = sum(1 for l in leads if l.status == models.LeadStatus.HELD)
    qa_review = sum(1 for l in leads if l.status == models.LeadStatus.QA_REVIEW)
    pending = sum(1 for l in leads if l.status == models.LeadStatus.PENDING_SCORE)

    all_scores = db.query(models.ScoreResult).all()
    critical_scores = [s for s in all_scores if s.critical]
    critical_failure_rate = (
        round(sum(1 for s in critical_scores if s.result == models.ResultType.FAIL) / len(critical_scores), 4)
        if critical_scores else 0.0
    )

    total_rule_slots = 0
    for lead in leads:
        total_rule_slots += len(rule_service.get_active_rules(db, lead.retailer, lead.call_date.date()))
    checklist_coverage = round(len(all_scores) / total_rule_slots, 4) if total_rule_slots else 0.0

    metrics = evaluation_service.compute_metrics(db)

    summaries = [build_lead_summary(db, lead) for lead in leads[:10]]

    return schemas.DashboardSummary(
        total_sales=total,
        ready_to_submit=ready,
        held=held,
        qa_review=qa_review,
        pending_score=pending,
        critical_failure_rate=critical_failure_rate,
        checklist_coverage=checklist_coverage,
        human_auditor_agreement_rate=metrics.overall_agreement_rate,
        critical_false_pass_count=metrics.critical_false_pass_count,
        recent_leads=summaries,
    )
