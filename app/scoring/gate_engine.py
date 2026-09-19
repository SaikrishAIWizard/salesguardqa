"""
Deterministic gate logic plus the evidence guardrail.

Guardrail: a critical PASS or FAIL is downgraded to REVIEW whenever the
evidence it rests on is itself uncertain (an UNKNOWN/OVERLAP speaker
segment, or a transcript segment below the confidence threshold). This
prevents crosstalk or a garbled segment from silently producing a false
critical pass or fail.

Gate:
  any critical FAIL   -> HELD
  any critical REVIEW -> QA_REVIEW
  otherwise            -> READY_TO_SUBMIT
"""
from typing import Dict, List

from ..models import Speaker, TranscriptSegment

LOW_CONFIDENCE_THRESHOLD = 0.80


def apply_evidence_guardrail(outcome, critical: bool, segments_by_id: Dict[int, TranscriptSegment]):
    if not critical or outcome.result == "REVIEW":
        return outcome

    seg = segments_by_id.get(outcome.segment_id) if outcome.segment_id else None
    if seg is None:
        return outcome

    uncertain_speaker = seg.speaker in (Speaker.UNKNOWN, Speaker.OVERLAP)
    low_confidence = (
        seg.transcription_confidence is not None
        and seg.transcription_confidence < LOW_CONFIDENCE_THRESHOLD
    )

    if not (uncertain_speaker or low_confidence):
        return outcome

    reasons = []
    if uncertain_speaker:
        reasons.append(f"evidence segment speaker is {seg.speaker.value}")
    if low_confidence:
        reasons.append(f"transcription confidence {seg.transcription_confidence:.2f} is below {LOW_CONFIDENCE_THRESHOLD:.2f}")

    original_result = outcome.result
    outcome.result = "REVIEW"
    outcome.confidence = min(outcome.confidence, 0.6)
    outcome.reason = (
        f"{outcome.reason} Guardrail: downgraded from {original_result} to REVIEW because "
        f"{', '.join(reasons)} - routed to human QA rather than trusting uncertain evidence."
    )
    return outcome


def compute_gate_status(critical_results: List[str]) -> str:
    """critical_results: the `result` field of every CRITICAL score result."""
    if any(r == "FAIL" for r in critical_results):
        return "HELD"
    if any(r == "REVIEW" for r in critical_results):
        return "QA_REVIEW"
    return "READY_TO_SUBMIT"
