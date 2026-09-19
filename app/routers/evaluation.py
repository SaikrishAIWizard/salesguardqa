from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import schemas
from ..database import get_db
from ..services import evaluation_service

router = APIRouter(tags=["evaluation"])


@router.get("/evaluation/metrics", response_model=schemas.EvaluationMetrics)
def evaluation_metrics(db: Session = Depends(get_db)):
    return evaluation_service.compute_metrics(db)
