from typing import List, Optional
from sqlalchemy.orm import Session

from .. import models, schemas


def get_lead(db: Session, lead_id: str) -> Optional[models.Lead]:
    return db.query(models.Lead).filter(models.Lead.id == lead_id).first()


def list_leads(db: Session) -> List[models.Lead]:
    return db.query(models.Lead).order_by(models.Lead.call_date.desc()).all()


def ingest_call(db: Session, payload: schemas.LeadIngestIn, source: str = "INGESTED") -> models.Lead:
    lead = get_lead(db, payload.id)
    if lead is None:
        lead = models.Lead(id=payload.id, source=source)
        db.add(lead)

    lead.retailer = payload.retailer
    lead.customer_name = payload.customer_name
    lead.account_holder_name = payload.account_holder_name
    lead.email = payload.email
    lead.address = payload.address
    lead.plan_id = payload.plan_id
    lead.call_date = payload.call_date
    lead.agent_name = payload.agent_name
    lead.audio_path = payload.audio_path
    lead.status = models.LeadStatus.PENDING_SCORE

    # Replace any existing segments for a re-ingested lead.
    db.query(models.TranscriptSegment).filter(models.TranscriptSegment.lead_id == lead.id).delete()
    for seg in payload.segments:
        db.add(models.TranscriptSegment(
            lead_id=lead.id,
            speaker=models.Speaker(seg.speaker),
            start_seconds=seg.start_seconds,
            end_seconds=seg.end_seconds,
            text=seg.text,
            transcription_confidence=seg.transcription_confidence,
        ))

    db.commit()
    db.refresh(lead)
    return lead


def delete_lead(db: Session, lead: models.Lead) -> None:
    """Deletes a lead and, via ORM cascades, its transcript, scores, overrides and audits."""
    db.delete(lead)
    db.commit()
