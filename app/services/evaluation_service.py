from collections import Counter
from sqlalchemy.orm import Session

from .. import models, schemas


def compute_metrics(db: Session) -> schemas.EvaluationMetrics:
    audits = db.query(models.HumanAudit).all()

    total = 0
    agree = 0
    critical_total = 0
    critical_agree = 0
    critical_false_pass = 0
    critical_false_fail = 0
    confusion = Counter()

    for audit in audits:
        # Latest automated score for this lead + rule.
        score = (
            db.query(models.ScoreResult)
            .filter(models.ScoreResult.lead_id == audit.lead_id, models.ScoreResult.rule_id == audit.rule_id)
            .order_by(models.ScoreResult.id.desc())
            .first()
        )
        if score is None:
            continue

        total += 1
        automated_result = score.result.value
        human_result = audit.auditor_result.value
        confusion[(automated_result, human_result)] += 1

        if automated_result == human_result:
            agree += 1

        if score.critical:
            critical_total += 1
            if automated_result == human_result:
                critical_agree += 1
            if automated_result == "PASS" and human_result == "FAIL":
                critical_false_pass += 1
            if automated_result == "FAIL" and human_result == "PASS":
                critical_false_fail += 1

    overall_rate = round(agree / total, 4) if total else 0.0
    critical_rate = round(critical_agree / critical_total, 4) if critical_total else 0.0

    confusion_matrix = [
        schemas.ConfusionCell(automated=a, human=h, count=c)
        for (a, h), c in sorted(confusion.items())
    ]

    return schemas.EvaluationMetrics(
        total_audited_checks=total,
        overall_agreement_rate=overall_rate,
        critical_agreement_rate=critical_rate,
        critical_false_pass_count=critical_false_pass,
        critical_false_fail_count=critical_false_fail,
        confusion_matrix=confusion_matrix,
    )
