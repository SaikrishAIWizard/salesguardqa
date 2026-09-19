from datetime import date
from typing import List
from sqlalchemy.orm import Session

from .. import models


def get_active_rules(db: Session, retailer: str, call_date: date) -> List[models.ChecklistRule]:
    """Returns the checklist rules whose version was in effect on the call
    date - never today's version. A rule is active when
    effective_from <= call_date and (effective_to is null or call_date <= effective_to)."""
    query = (
        db.query(models.ChecklistRule)
        .filter(models.ChecklistRule.retailer == retailer)
        .filter(models.ChecklistRule.effective_from <= call_date)
        .filter(
            (models.ChecklistRule.effective_to.is_(None))
            | (models.ChecklistRule.effective_to >= call_date)
        )
        .order_by(models.ChecklistRule.check_type, models.ChecklistRule.id)
    )
    return query.all()


def get_rule(db: Session, rule_id: str) -> models.ChecklistRule:
    return db.query(models.ChecklistRule).filter(models.ChecklistRule.id == rule_id).first()
