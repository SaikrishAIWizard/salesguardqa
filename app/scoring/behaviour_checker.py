"""
Behaviour checker - transcript-only, non-critical signals.

These checks never block a sale on their own (they are always non-critical)
and must never manufacture a failure from uncertain data - absence of a
signal is simply PASS.
"""
from dataclasses import dataclass
from typing import List, Optional

from ..models import ChecklistRule, TranscriptSegment, Speaker
from ..services import llm_service


@dataclass
class CheckOutcome:
    result: str
    confidence: float
    evidence_text: Optional[str]
    segment_id: Optional[int]
    timestamp_seconds: Optional[int]
    reason: str
    evaluation_method: str
    expected_value: Optional[str] = None
    actual_value: Optional[str] = None


def _check_dead_air(rule: ChecklistRule, segments: List[TranscriptSegment]) -> CheckOutcome:
    threshold = rule.matching_config_json.get("threshold_seconds", 30)
    ordered = sorted(segments, key=lambda s: s.start_seconds)

    for prev_seg, next_seg in zip(ordered, ordered[1:]):
        gap = next_seg.start_seconds - prev_seg.end_seconds
        if gap > threshold:
            return CheckOutcome(
                result="FAIL",
                confidence=1.0,
                evidence_text=f"Silence from {prev_seg.end_seconds}s to {next_seg.start_seconds}s",
                segment_id=prev_seg.id,
                timestamp_seconds=prev_seg.end_seconds,
                reason=f"Coaching note: {gap} seconds of dead air detected, exceeding the {threshold}s threshold.",
                evaluation_method="DETERMINISTIC",
                expected_value=f"<= {threshold}s gap",
                actual_value=f"{gap}s gap",
            )

    return CheckOutcome(
        result="PASS",
        confidence=1.0,
        evidence_text=None,
        segment_id=None,
        timestamp_seconds=None,
        reason=f"No silence gap exceeded the {threshold}s threshold.",
        evaluation_method="DETERMINISTIC",
    )


def _check_crosstalk(rule: ChecklistRule, segments: List[TranscriptSegment]) -> CheckOutcome:
    confidence_threshold = rule.matching_config_json.get("confidence_threshold", 0.80)
    ordered = sorted(segments, key=lambda s: s.start_seconds)

    for seg in ordered:
        if seg.speaker in (Speaker.UNKNOWN, Speaker.OVERLAP):
            return CheckOutcome(
                result="FAIL",
                confidence=1.0,
                evidence_text=seg.text,
                segment_id=seg.id,
                timestamp_seconds=seg.start_seconds,
                reason=f"QA signal: segment {seg.id} has speaker '{seg.speaker.value}' (crosstalk / unidentified speaker).",
                evaluation_method="DETERMINISTIC",
            )
        if seg.transcription_confidence is not None and seg.transcription_confidence < confidence_threshold:
            return CheckOutcome(
                result="FAIL",
                confidence=1.0,
                evidence_text=seg.text,
                segment_id=seg.id,
                timestamp_seconds=seg.start_seconds,
                reason=f"QA signal: segment {seg.id} transcription confidence {seg.transcription_confidence:.2f} "
                       f"is below the {confidence_threshold:.2f} threshold.",
                evaluation_method="DETERMINISTIC",
            )

    return CheckOutcome(
        result="PASS",
        confidence=1.0,
        evidence_text=None,
        segment_id=None,
        timestamp_seconds=None,
        reason="No crosstalk, unidentified speaker, or low-confidence segments detected.",
        evaluation_method="DETERMINISTIC",
    )


def check_behaviour_rule(rule: ChecklistRule, segments: List[TranscriptSegment]) -> CheckOutcome:
    behaviour_type = rule.matching_config_json.get("type")

    if behaviour_type == "dead_air":
        outcome = _check_dead_air(rule, segments)
    elif behaviour_type == "crosstalk_low_confidence":
        outcome = _check_crosstalk(rule, segments)
    else:
        return CheckOutcome(
            result="REVIEW",
            confidence=0.0,
            evidence_text=None,
            segment_id=None,
            timestamp_seconds=None,
            reason=f"Unknown behaviour check type '{behaviour_type}'.",
            evaluation_method="DETERMINISTIC",
        )

    if outcome.result == "PASS":
        agent_text = " ".join(s.text for s in segments if s.speaker == Speaker.AGENT)
        customer_text = " ".join(s.text for s in segments if s.speaker == Speaker.CUSTOMER)
        note = llm_service.behaviour_note(agent_text, customer_text)
        if note:
            outcome.reason = f"{outcome.reason} LLM note: {note}"
            outcome.evaluation_method = "LLM_SEMANTIC"

    return outcome
