from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..services import lead_service
from ..services.scoring_service import score_lead, ScoringError

router = APIRouter(tags=["scoring"])


@router.post("/leads/score-all", response_model=schemas.ScoreAllResponse)
def score_all(db: Session = Depends(get_db)):
    """Re-scores every lead. One lead failing never stops the rest."""
    items = []
    for lead in lead_service.list_leads(db):
        lead_id = lead.id
        try:
            items.append(schemas.ScoreAllItem(lead_id=lead_id, status=str(score_lead(db, lead))))
        except Exception as exc:  # batch: record the failure and carry on
            db.rollback()
            items.append(schemas.ScoreAllItem(lead_id=lead_id, error=str(exc)))
    failed = sum(1 for i in items if i.error)
    return schemas.ScoreAllResponse(total=len(items), scored=len(items) - failed, failed=failed, results=items)


@router.post("/leads/{lead_id}/score", response_model=schemas.ScoreSaleResponse)
def score_sale(lead_id: str, db: Session = Depends(get_db)):
    lead = lead_service.get_lead(db, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")

    try:
        final_status = score_lead(db, lead)
    except ScoringError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    results = (
        db.query(models.ScoreResult)
        .filter(models.ScoreResult.lead_id == lead_id)
        .order_by(models.ScoreResult.check_type, models.ScoreResult.rule_id)
        .all()
    )
    return schemas.ScoreSaleResponse(
        lead_id=lead_id,
        status=final_status,
        results=[schemas.ScoreResultOut.model_validate(r) for r in results],
    )


@router.get("/leads/{lead_id}/scores", response_model=list[schemas.ScoreResultOut])
def get_scores(lead_id: str, db: Session = Depends(get_db)):
    lead = lead_service.get_lead(db, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    scores = (
        db.query(models.ScoreResult)
        .filter(models.ScoreResult.lead_id == lead_id)
        .order_by(models.ScoreResult.check_type, models.ScoreResult.rule_id)
        .all()
    )
    return scores
