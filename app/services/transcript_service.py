from typing import List
from sqlalchemy.orm import Session

from .. import models, schemas
from .redaction_service import redact_card_numbers


def get_segments(db: Session, lead_id: str) -> List[models.TranscriptSegment]:
    segments = (
        db.query(models.TranscriptSegment)
        .filter(models.TranscriptSegment.lead_id == lead_id)
        .order_by(models.TranscriptSegment.start_seconds)
        .all()
    )
    return segments


def to_redacted_schema(segments: List[models.TranscriptSegment]) -> List[schemas.TranscriptSegmentOut]:
    """Builds output schemas with card-number-like sequences redacted in text.
    Never mutates the ORM objects, so the database is never touched by redaction."""
    return [
        schemas.TranscriptSegmentOut(
            id=seg.id,
            speaker=seg.speaker.value,
            start_seconds=seg.start_seconds,
            end_seconds=seg.end_seconds,
            text=redact_card_numbers(seg.text),
            transcription_confidence=seg.transcription_confidence,
        )
        for seg in segments
    ]
