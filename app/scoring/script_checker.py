"""
Script / compliance checker.

Flow (per the product spec):
  1. Python normalised exact match -> clear match => PASS
  2. Python approved-variant / fuzzy match, confidence >= 0.90 => PASS
  3. Uncertain wording -> optional LLM semantic fallback
       - clearly fulfils, confidence >= 0.95 => PASS
       - clearly fails,   confidence >= 0.95 => FAIL
       - otherwise => REVIEW
  4. No LLM key and Python matching uncertain => REVIEW

A script rule is never failed purely because an exact phrase was absent.
"""
import difflib
import re
from dataclasses import dataclass
from typing import List, Optional

from ..models import ChecklistRule, TranscriptSegment, Speaker
from ..services import llm_service

FUZZY_PASS_THRESHOLD = 0.90
LLM_CONFIDENT_THRESHOLD = 0.95


@dataclass
class CheckOutcome:
    result: str  # PASS | FAIL | REVIEW
    confidence: float
    evidence_text: Optional[str]
    segment_id: Optional[int]
    timestamp_seconds: Optional[int]
    reason: str
    evaluation_method: str
    expected_value: Optional[str] = None
    actual_value: Optional[str] = None


def _normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _best_variant_match(agent_segments: List[TranscriptSegment], variants: List[str]):
    """Returns (ratio, segment, variant, exact) for the best match across all agent segments."""
    best_ratio = 0.0
    best_segment = None
    best_variant = None
    exact = False

    for seg in agent_segments:
        norm_seg = _normalize(seg.text)
        if not norm_seg:
            continue
        for variant in variants:
            norm_variant = _normalize(variant)
            if norm_variant and norm_variant in norm_seg:
                return 1.0, seg, variant, True
            ratio = difflib.SequenceMatcher(None, norm_seg, norm_variant).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_segment = seg
                best_variant = variant

    return best_ratio, best_segment, best_variant, exact


def check_script_rule(rule: ChecklistRule, segments: List[TranscriptSegment]) -> CheckOutcome:
    # OVERLAP segments may still carry the agent's words (crosstalk), so they
    # remain candidates for evidence; the gate engine's guardrail is what
    # downgrades a critical result resting on such uncertain evidence.
    agent_segments = [s for s in segments if s.speaker in (Speaker.AGENT, Speaker.OVERLAP)]
    variants = rule.matching_config_json.get("approved_variants", [])

    ratio, segment, variant, exact = _best_variant_match(agent_segments, variants)

    if exact or ratio >= FUZZY_PASS_THRESHOLD:
        confidence = 1.0 if exact else round(ratio, 2)
        return CheckOutcome(
            result="PASS",
            confidence=confidence,
            evidence_text=segment.text if segment else None,
            segment_id=segment.id if segment else None,
            timestamp_seconds=segment.start_seconds if segment else None,
            reason=f"Matched approved wording ({'exact' if exact else f'fuzzy {confidence:.2f}'}) for '{rule.name}'.",
            evaluation_method="DETERMINISTIC",
        )

    # Uncertain - try optional LLM semantic fallback.
    agent_full_text = " ".join(s.text for s in agent_segments)
    llm_result = llm_service.semantic_script_check(rule.name, rule.description, agent_full_text)

    if llm_result is not None:
        verdict, llm_confidence = llm_result
        if verdict == "FULFILLS" and llm_confidence >= LLM_CONFIDENT_THRESHOLD:
            return CheckOutcome(
                result="PASS",
                confidence=llm_confidence,
                evidence_text=segment.text if segment else agent_full_text[:200],
                segment_id=segment.id if segment else None,
                timestamp_seconds=segment.start_seconds if segment else None,
                reason=f"LLM semantic check found wording fulfils intent of '{rule.name}'.",
                evaluation_method="LLM_SEMANTIC",
            )
        if verdict == "DOES_NOT_FULFILL" and llm_confidence >= LLM_CONFIDENT_THRESHOLD:
            return CheckOutcome(
                result="FAIL",
                confidence=llm_confidence,
                evidence_text=segment.text if segment else agent_full_text[:200],
                segment_id=segment.id if segment else None,
                timestamp_seconds=segment.start_seconds if segment else None,
                reason=f"LLM semantic check found wording does not fulfil intent of '{rule.name}'.",
                evaluation_method="LLM_SEMANTIC",
            )
        return CheckOutcome(
            result="REVIEW",
            confidence=llm_confidence,
            evidence_text=segment.text if segment else None,
            segment_id=segment.id if segment else None,
            timestamp_seconds=segment.start_seconds if segment else None,
            reason=f"LLM semantic check was inconclusive for '{rule.name}'; routed to human QA.",
            evaluation_method="LLM_SEMANTIC",
        )

    # No LLM available, Python matching uncertain -> REVIEW, never a silent pass/fail.
    return CheckOutcome(
        result="REVIEW",
        confidence=round(ratio, 2),
        evidence_text=segment.text if segment else None,
        segment_id=segment.id if segment else None,
        timestamp_seconds=segment.start_seconds if segment else None,
        reason=f"No confident match for '{rule.name}' and no LLM fallback configured; routed to human QA.",
        evaluation_method="DETERMINISTIC",
    )
