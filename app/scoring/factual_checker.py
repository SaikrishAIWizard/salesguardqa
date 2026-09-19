"""
Factual checker - deterministic extraction and comparison only.

The LLM is never used to decide factual equality. A confidently-extracted
mismatch is always FAIL; an unclear or absent value is always REVIEW; a
confidently-extracted match is PASS.
"""
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

from ..models import ChecklistRule, TranscriptSegment, Lead, Plan, Speaker

RATE_TOLERANCE_CENTS = 0.05

_NUM_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
    "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40,
    "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}


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


def _normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9.\s@]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _normalize_tokens(text: str) -> str:
    """Like _normalize but strips ALL punctuation, for token-set overlap
    comparisons where a trailing period must not break a word match."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _words_to_number(phrase: str) -> Optional[float]:
    """Parses phrases like 'twenty eight point six' -> 28.6."""
    phrase = phrase.strip().lower()
    if "point" in phrase:
        whole_part, _, frac_part = phrase.partition("point")
    else:
        whole_part, frac_part = phrase, ""

    def parse_whole(words: str) -> Optional[int]:
        tokens = words.split()
        if not tokens:
            return None
        total = 0
        matched = False
        i = 0
        while i < len(tokens):
            tok = tokens[i]
            if tok in _NUM_WORDS:
                val = _NUM_WORDS[tok]
                if val >= 20 and i + 1 < len(tokens) and tokens[i + 1] in _NUM_WORDS and _NUM_WORDS[tokens[i + 1]] < 10:
                    total += val + _NUM_WORDS[tokens[i + 1]]
                    i += 2
                else:
                    total += val
                    i += 1
                matched = True
            else:
                i += 1
        return total if matched else None

    whole = parse_whole(whole_part)
    if whole is None:
        return None
    if not frac_part.strip():
        return float(whole)
    frac_digits = "".join(str(_NUM_WORDS[t]) for t in frac_part.split() if t in _NUM_WORDS)
    if not frac_digits:
        return float(whole)
    return float(f"{whole}.{frac_digits}")


def _extract_rate_from_text(text: str) -> Optional[float]:
    norm = _normalize(text)
    match = re.search(r"(\d+(?:\.\d+)?)\s*(?:cents?|c)\b", norm)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass
    match = re.search(r"([a-z\s]+?point[a-z\s]+?)\s*(?:cents?|c)\b", norm)
    if match:
        val = _words_to_number(match.group(1))
        if val is not None:
            return val
    return None


def _extract_email_from_text(text: str) -> Optional[str]:
    norm = _normalize(text)
    direct = re.search(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}", norm)
    if direct:
        return direct.group(0)
    spoken = re.search(
        r"([a-z0-9]+(?:\s+dot\s+[a-z0-9]+)*)\s+at\s+([a-z0-9]+(?:\s+dot\s+[a-z0-9]+)+)",
        norm,
    )
    if spoken:
        local = spoken.group(1).replace(" dot ", ".").replace(" ", ".")
        domain = spoken.group(2).replace(" dot ", ".").replace(" ", ".")
        return f"{local}@{domain}"
    return None


def _token_overlap(expected: str, candidate: str) -> float:
    exp_tokens = set(_normalize_tokens(expected).split())
    cand_tokens = set(_normalize_tokens(candidate).split())
    if not exp_tokens:
        return 0.0
    return len(exp_tokens & cand_tokens) / len(exp_tokens)


def _rate_outcome(rule: ChecklistRule, segments: List[TranscriptSegment], plan: Plan, field: str) -> CheckOutcome:
    keyword = "off peak" if field == "off_peak_rate" else "peak"
    exclude = field != "off_peak_rate"
    agent_segments = [s for s in segments if s.speaker in (Speaker.AGENT, Speaker.OVERLAP)]

    candidate_segment = None
    extracted_value = None
    for seg in agent_segments:
        norm = _normalize(seg.text)
        has_offpeak = "off peak" in norm or "off-peak" in norm
        if field == "off_peak_rate" and not has_offpeak:
            continue
        if field == "peak_rate" and has_offpeak:
            continue
        if "rate" not in norm and "cent" not in norm and "peak" not in norm:
            continue
        val = _extract_rate_from_text(seg.text)
        if val is not None:
            candidate_segment = seg
            extracted_value = val
            break

    official_rate = plan.peak_rate_cents if field == "peak_rate" else plan.off_peak_rate_cents

    if extracted_value is None:
        return CheckOutcome(
            result="REVIEW",
            confidence=0.4,
            evidence_text=None,
            segment_id=None,
            timestamp_seconds=None,
            reason=f"Could not confidently extract a spoken {field.replace('_', ' ')} value; routed to human QA.",
            evaluation_method="DETERMINISTIC",
            expected_value=f"{official_rate} cents/kWh",
            actual_value=None,
        )

    diff = abs(extracted_value - official_rate)
    if diff <= RATE_TOLERANCE_CENTS:
        return CheckOutcome(
            result="PASS",
            confidence=1.0,
            evidence_text=candidate_segment.text,
            segment_id=candidate_segment.id,
            timestamp_seconds=candidate_segment.start_seconds,
            reason=f"Spoken rate {extracted_value} cents matches plan rate {official_rate} cents.",
            evaluation_method="DETERMINISTIC",
            expected_value=f"{official_rate} cents/kWh",
            actual_value=f"{extracted_value} cents/kWh",
        )

    return CheckOutcome(
        result="FAIL",
        confidence=1.0,
        evidence_text=candidate_segment.text,
        segment_id=candidate_segment.id,
        timestamp_seconds=candidate_segment.start_seconds,
        reason=f"Spoken rate {extracted_value} cents does not match plan rate {official_rate} cents (diff {diff:.2f}).",
        evaluation_method="DETERMINISTIC",
        expected_value=f"{official_rate} cents/kWh",
        actual_value=f"{extracted_value} cents/kWh",
    )


def _email_outcome(segments: List[TranscriptSegment], lead: Lead) -> CheckOutcome:
    agent_segments = [s for s in segments if s.speaker in (Speaker.AGENT, Speaker.OVERLAP)]
    candidate_segment = None
    extracted_email = None
    for seg in agent_segments:
        if "email" not in _normalize(seg.text) and "@" not in seg.text and " at " not in _normalize(seg.text):
            continue
        email = _extract_email_from_text(seg.text)
        if email:
            candidate_segment = seg
            extracted_email = email
            break

    crm_email = lead.email.strip().lower()

    if extracted_email is None:
        return CheckOutcome(
            result="REVIEW",
            confidence=0.4,
            evidence_text=None,
            segment_id=None,
            timestamp_seconds=None,
            reason="Could not confidently extract a spoken email read-back; routed to human QA.",
            evaluation_method="DETERMINISTIC",
            expected_value=crm_email,
            actual_value=None,
        )

    if extracted_email == crm_email:
        return CheckOutcome(
            result="PASS",
            confidence=1.0,
            evidence_text=candidate_segment.text,
            segment_id=candidate_segment.id,
            timestamp_seconds=candidate_segment.start_seconds,
            reason="Spoken email read-back matches CRM email.",
            evaluation_method="DETERMINISTIC",
            expected_value=crm_email,
            actual_value=extracted_email,
        )

    return CheckOutcome(
        result="FAIL",
        confidence=1.0,
        evidence_text=candidate_segment.text,
        segment_id=candidate_segment.id,
        timestamp_seconds=candidate_segment.start_seconds,
        reason=f"Spoken email '{extracted_email}' does not match CRM email '{crm_email}'.",
        evaluation_method="DETERMINISTIC",
        expected_value=crm_email,
        actual_value=extracted_email,
    )


def _text_field_outcome(rule: ChecklistRule, segments: List[TranscriptSegment], expected: str, keyword_hints: List[str]) -> CheckOutcome:
    agent_segments = [s for s in segments if s.speaker in (Speaker.AGENT, Speaker.OVERLAP)]
    candidate_segment = None
    best_overlap = 0.0

    for seg in agent_segments:
        norm = _normalize(seg.text)
        if not any(k in norm for k in keyword_hints):
            continue
        overlap = _token_overlap(expected, seg.text)
        if overlap > best_overlap:
            best_overlap = overlap
            candidate_segment = seg

    if candidate_segment is None:
        return CheckOutcome(
            result="REVIEW",
            confidence=0.3,
            evidence_text=None,
            segment_id=None,
            timestamp_seconds=None,
            reason=f"No segment confidently references the {rule.name.lower().replace('_', ' ')}; routed to human QA.",
            evaluation_method="DETERMINISTIC",
            expected_value=expected,
            actual_value=None,
        )

    if best_overlap >= 0.8:
        return CheckOutcome(
            result="PASS",
            confidence=round(best_overlap, 2),
            evidence_text=candidate_segment.text,
            segment_id=candidate_segment.id,
            timestamp_seconds=candidate_segment.start_seconds,
            reason=f"Spoken value matches CRM value for '{rule.name}'.",
            evaluation_method="DETERMINISTIC",
            expected_value=expected,
            actual_value=candidate_segment.text,
        )

    if best_overlap >= 0.4:
        return CheckOutcome(
            result="FAIL",
            confidence=round(1 - best_overlap, 2) + 0.4,
            evidence_text=candidate_segment.text,
            segment_id=candidate_segment.id,
            timestamp_seconds=candidate_segment.start_seconds,
            reason=f"Spoken value differs from CRM value for '{rule.name}'.",
            evaluation_method="DETERMINISTIC",
            expected_value=expected,
            actual_value=candidate_segment.text,
        )

    return CheckOutcome(
        result="REVIEW",
        confidence=0.4,
        evidence_text=candidate_segment.text,
        segment_id=candidate_segment.id,
        timestamp_seconds=candidate_segment.start_seconds,
        reason=f"Spoken value for '{rule.name}' is unclear relative to CRM value; routed to human QA.",
        evaluation_method="DETERMINISTIC",
        expected_value=expected,
        actual_value=candidate_segment.text,
    )


def check_factual_rule(rule: ChecklistRule, segments: List[TranscriptSegment], lead: Lead, plan: Plan) -> CheckOutcome:
    field = rule.matching_config_json.get("field")

    if field == "peak_rate":
        return _rate_outcome(rule, segments, plan, "peak_rate")
    if field == "off_peak_rate":
        return _rate_outcome(rule, segments, plan, "off_peak_rate")
    if field == "email":
        return _email_outcome(segments, lead)
    if field == "address":
        return _text_field_outcome(rule, segments, lead.address, ["address"])
    if field == "plan_name":
        return _text_field_outcome(rule, segments, plan.plan_name, ["plan"])

    return CheckOutcome(
        result="REVIEW",
        confidence=0.0,
        evidence_text=None,
        segment_id=None,
        timestamp_seconds=None,
        reason=f"Unknown factual field '{field}' in rule configuration.",
        evaluation_method="DETERMINISTIC",
    )
