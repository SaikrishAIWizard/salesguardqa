from sqlalchemy.orm import Session

from .. import models
from . import transcript_service, rule_service
from .redaction_service import redact_card_numbers
from ..scoring import script_checker, factual_checker, behaviour_checker, gate_engine


class ScoringError(ValueError):
    pass


def _dispatch(rule: models.ChecklistRule, segments, lead, plan):
    if rule.check_type == models.CheckType.SCRIPT:
        return script_checker.check_script_rule(rule, segments)
    if rule.check_type == models.CheckType.FACTUAL:
        return factual_checker.check_factual_rule(rule, segments, lead, plan)
    if rule.check_type == models.CheckType.BEHAVIOUR:
        return behaviour_checker.check_behaviour_rule(rule, segments)
    raise ScoringError(f"Unknown check_type {rule.check_type}")


def score_lead(db: Session, lead: models.Lead) -> str:
    """Scores a lead against its retailer's active checklist, persists the
    score_results, updates lead.status, and returns the final status string.
    Raises ScoringError if the lead cannot be scored (no plan/segments/rules)."""
    if lead.plan is None:
        raise ScoringError("Lead has no associated plan; cannot score.")

    segments = transcript_service.get_segments(db, lead.id)
    if not segments:
        raise ScoringError("Lead has no transcript segments; cannot score.")

    segments_by_id = {s.id: s for s in segments}
    rules = rule_service.get_active_rules(db, lead.retailer, lead.call_date.date())
    if not rules:
        raise ScoringError(f"No checklist rules active for {lead.retailer} on {lead.call_date.date()}.")

    db.query(models.ScoreResult).filter(models.ScoreResult.lead_id == lead.id).delete()

    critical_results = []
    for rule in rules:
        outcome = _dispatch(rule, segments, lead, lead.plan)
        outcome = gate_engine.apply_evidence_guardrail(outcome, rule.critical, segments_by_id)

        if rule.critical:
            critical_results.append(outcome.result)

        db.add(models.ScoreResult(
            lead_id=lead.id,
            rule_id=rule.id,
            rule_name=rule.name,
            check_type=rule.check_type,
            result=models.ResultType(outcome.result),
            critical=rule.critical,
            confidence=outcome.confidence,
            transcript_segment_id=outcome.segment_id,
            evidence_text=redact_card_numbers(outcome.evidence_text) if outcome.evidence_text else outcome.evidence_text,
            timestamp_seconds=outcome.timestamp_seconds,
            expected_value=outcome.expected_value,
            actual_value=outcome.actual_value,
            reason=outcome.reason,
            rule_version=rule.version,
            evaluation_method=models.EvaluationMethod(outcome.evaluation_method),
        ))

    final_status = gate_engine.compute_gate_status(critical_results)
    lead.status = models.LeadStatus(final_status)
    db.commit()
    return final_status
