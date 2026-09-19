"""
Seeds synthetic demo data: plans, the Retailer 1 checklist, five leads with
transcripts engineered to exercise every scoring path, human-auditor ground
truth for evaluation metrics, and an initial automated score for each lead.

Test data only - no real customer PII, per the guardrails in the brief.
"""
import json
import os
from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from . import models
from .services.scoring_service import score_lead

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def _load_rules() -> list[dict]:
    with open(os.path.join(DATA_DIR, "retailer_1_rules.json"), "r", encoding="utf-8") as f:
        return json.load(f)


def _seed_rules(db: Session):
    for row in _load_rules():
        db.add(models.ChecklistRule(
            id=row["id"],
            retailer=row["retailer"],
            name=row["name"],
            description=row["description"],
            check_type=models.CheckType(row["check_type"]),
            critical=row["critical"],
            version=row["version"],
            effective_from=date.fromisoformat(row["effective_from"]),
            effective_to=date.fromisoformat(row["effective_to"]) if row.get("effective_to") else None,
            matching_config_json=row["matching_config_json"],
        ))
    db.commit()


def _seed_plans(db: Session):
    db.add(models.Plan(
        id="ENERGY-101",
        retailer="Retailer 1",
        plan_name="Flexi Saver Plan",
        peak_rate_cents=31.9,
        off_peak_rate_cents=21.4,
        effective_from=date(2026, 1, 1),
        effective_to=None,
    ))
    db.commit()


def _pack_segments(lead_id: str, spec: list[dict]) -> list[models.TranscriptSegment]:
    """Lays out segments sequentially. Each item may set `gap_before` (seconds
    of silence before this segment starts, default 5) and `duration`
    (default derived from text length). A large gap_before is how a dead-air
    scenario is created; everything else stays tightly packed so no
    unintended dead-air gap appears."""
    segments = []
    t = 5
    for item in spec:
        gap = item.get("gap_before", 5)
        t += gap
        duration = item.get("duration", max(3, len(item["text"]) // 12))
        start = t
        end = t + duration
        segments.append(models.TranscriptSegment(
            lead_id=lead_id,
            speaker=models.Speaker(item["speaker"]),
            start_seconds=start,
            end_seconds=end,
            text=item["text"],
            transcription_confidence=item.get("confidence", 0.95),
        ))
        t = end
    return segments


def _add_lead(db: Session, lead_kwargs: dict, segment_spec: list[dict], expected_results: dict[str, str]):
    lead = models.Lead(status=models.LeadStatus.PENDING_SCORE, **lead_kwargs)
    db.add(lead)
    db.commit()

    for seg in _pack_segments(lead.id, segment_spec):
        db.add(seg)
    db.commit()

    for rule_id, auditor_result in expected_results.items():
        db.add(models.HumanAudit(
            lead_id=lead.id,
            rule_id=rule_id,
            auditor_result=models.ResultType(auditor_result),
            auditor_note="Seeded ground truth from manual audit review.",
            reviewed_at=datetime.now(timezone.utc),
        ))
    db.commit()

    db.refresh(lead)
    score_lead(db, lead)


def seed_if_empty(db: Session):
    if db.query(models.Lead).count() > 0:
        return

    _seed_rules(db)
    _seed_plans(db)

    # ---------------------------------------------------------------
    # Lead 3613790 - HELD: rate mismatch + email mismatch + dead air note.
    # ---------------------------------------------------------------
    _add_lead(
        db,
        dict(
            id="3613790",
            retailer="Retailer 1",
            customer_name="John Smith",
            account_holder_name="John Smith",
            email="j.smith@gmial.com",
            address="22 Junction Street, Parramatta NSW 2150",
            plan_id="ENERGY-101",
            call_date=datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc),
            agent_name="Agent A",
            audio_path="/audio/3613790.mp3",
        ),
        [
            {"speaker": "AGENT", "text": "This call is being recorded for quality purposes.", "confidence": 0.95},
            {"speaker": "CUSTOMER", "text": "Okay, sure.", "confidence": 0.93},
            {"speaker": "AGENT", "text": "Can I confirm that I am speaking with John Smith, the account holder?", "confidence": 0.96},
            {"speaker": "CUSTOMER", "text": "Yes, that's me.", "confidence": 0.95},
            {"speaker": "AGENT", "text": "I will now read the required market offer disclosure.", "confidence": 0.97},
            {"speaker": "AGENT", "text": "This offer includes a conditional discount and the rates I am about to confirm.", "confidence": 0.9},
            {"speaker": "AGENT", "text": "Your peak electricity rate will be 28.6 cents per kilowatt hour.", "confidence": 0.95},
            {"speaker": "AGENT", "text": "Your off-peak rate will be 21.4 cents per kilowatt hour.", "confidence": 0.95},
            {"speaker": "AGENT", "text": "You will be on our Flexi Saver Plan.", "confidence": 0.95},
            {"speaker": "AGENT", "text": "Can I confirm your address is 22 Junction Street, Parramatta NSW 2150?", "confidence": 0.94},
            {"speaker": "CUSTOMER", "text": "Yes that's correct.", "confidence": 0.95},
            {"speaker": "AGENT", "text": "Do you have any questions before we continue?", "confidence": 0.9},
            {"speaker": "CUSTOMER", "text": "No, sorry, I was just thinking.", "confidence": 0.92, "gap_before": 47},
            {"speaker": "AGENT", "text": "No problem. Your email address is j dot smith at gmail dot com.", "confidence": 0.95},
            {"speaker": "AGENT", "text": "Do you understand and accept these terms?", "confidence": 0.96},
            {"speaker": "CUSTOMER", "text": "Yes, I do.", "confidence": 0.95},
            {"speaker": "AGENT", "text": "Thanks John, that completes our call.", "confidence": 0.95},
        ],
        {
            "RECORDING_CONSENT": "PASS",
            "ACCOUNT_HOLDER_CONFIRMED": "PASS",
            "MARKET_OFFER_DISCLOSURE": "PASS",
            "TERMS_ACKNOWLEDGEMENT": "PASS",
            "PEAK_RATE_MATCH": "FAIL",
            "OFF_PEAK_RATE_MATCH": "PASS",
            "EMAIL_READBACK_MATCH": "FAIL",
            "ADDRESS_MATCH": "PASS",
            "PLAN_NAME_MATCH": "PASS",
            "DEAD_AIR": "FAIL",
            "CROSSTALK_OR_LOW_CONFIDENCE": "PASS",
        },
    )

    # ---------------------------------------------------------------
    # Lead 3613791 - READY_TO_SUBMIT: clean sale, everything checks out.
    # ---------------------------------------------------------------
    _add_lead(
        db,
        dict(
            id="3613791",
            retailer="Retailer 1",
            customer_name="Priya Sharma",
            account_holder_name="Priya Sharma",
            email="priya.sharma@example.com",
            address="8 Lakeview Road, Chatswood NSW 2067",
            plan_id="ENERGY-101",
            call_date=datetime(2026, 9, 6, 11, 30, tzinfo=timezone.utc),
            agent_name="Agent B",
            audio_path="/audio/3613791.mp3",
        ),
        [
            {"speaker": "AGENT", "text": "This call is being recorded for quality purposes.", "confidence": 0.96},
            {"speaker": "CUSTOMER", "text": "Sure, go ahead.", "confidence": 0.95},
            {"speaker": "AGENT", "text": "Can I confirm that I am speaking with Priya Sharma, the account holder?", "confidence": 0.96},
            {"speaker": "CUSTOMER", "text": "Yes, speaking.", "confidence": 0.95},
            {"speaker": "AGENT", "text": "I will now read the required market offer disclosure.", "confidence": 0.96},
            {"speaker": "AGENT", "text": "This is a market offer with the following benefits and conditions.", "confidence": 0.93},
            {"speaker": "AGENT", "text": "Your peak electricity rate will be 31.9 cents per kilowatt hour.", "confidence": 0.96},
            {"speaker": "AGENT", "text": "Your off-peak rate will be 21.4 cents per kilowatt hour.", "confidence": 0.96},
            {"speaker": "AGENT", "text": "You will be on our Flexi Saver Plan.", "confidence": 0.96},
            {"speaker": "AGENT", "text": "Can I confirm your address is 8 Lakeview Road, Chatswood NSW 2067?", "confidence": 0.95},
            {"speaker": "CUSTOMER", "text": "Yes, that's right.", "confidence": 0.95},
            {"speaker": "AGENT", "text": "Your email address is priya dot sharma at example dot com.", "confidence": 0.96},
            {"speaker": "AGENT", "text": "Do you understand and accept these terms?", "confidence": 0.96},
            {"speaker": "CUSTOMER", "text": "Yes, I accept.", "confidence": 0.95},
            {"speaker": "AGENT", "text": "Thanks Priya, that's everything, enjoy the new plan.", "confidence": 0.96},
        ],
        {
            "RECORDING_CONSENT": "PASS",
            "ACCOUNT_HOLDER_CONFIRMED": "PASS",
            "MARKET_OFFER_DISCLOSURE": "PASS",
            "TERMS_ACKNOWLEDGEMENT": "PASS",
            "PEAK_RATE_MATCH": "PASS",
            "OFF_PEAK_RATE_MATCH": "PASS",
            "EMAIL_READBACK_MATCH": "PASS",
            "ADDRESS_MATCH": "PASS",
            "PLAN_NAME_MATCH": "PASS",
            "DEAD_AIR": "PASS",
            "CROSSTALK_OR_LOW_CONFIDENCE": "PASS",
        },
    )

    # ---------------------------------------------------------------
    # Lead 3613792 - QA_REVIEW: terms acknowledgement wording is ambiguous.
    # ---------------------------------------------------------------
    _add_lead(
        db,
        dict(
            id="3613792",
            retailer="Retailer 1",
            customer_name="Michael Chen",
            account_holder_name="Michael Chen",
            email="m.chen@example.com",
            address="5 Bridge Street, Ryde NSW 2112",
            plan_id="ENERGY-101",
            call_date=datetime(2026, 9, 7, 9, 15, tzinfo=timezone.utc),
            agent_name="Agent C",
            audio_path="/audio/3613792.mp3",
        ),
        [
            {"speaker": "AGENT", "text": "This call is being recorded for quality purposes.", "confidence": 0.96},
            {"speaker": "CUSTOMER", "text": "Okay.", "confidence": 0.95},
            {"speaker": "AGENT", "text": "Can I confirm that I am speaking with Michael Chen, the account holder?", "confidence": 0.95},
            {"speaker": "CUSTOMER", "text": "Yes, that's me.", "confidence": 0.95},
            {"speaker": "AGENT", "text": "I will now read the required market offer disclosure.", "confidence": 0.95},
            {"speaker": "AGENT", "text": "This is a market offer with a fixed benefit period.", "confidence": 0.93},
            {"speaker": "AGENT", "text": "Your peak electricity rate will be 31.9 cents per kilowatt hour.", "confidence": 0.96},
            {"speaker": "AGENT", "text": "Your off-peak rate will be 21.4 cents per kilowatt hour.", "confidence": 0.95},
            {"speaker": "AGENT", "text": "You will be on our Flexi Saver Plan.", "confidence": 0.95},
            {"speaker": "AGENT", "text": "Can I confirm your address is 5 Bridge Street, Ryde NSW 2112?", "confidence": 0.95},
            {"speaker": "CUSTOMER", "text": "Yep, correct.", "confidence": 0.95},
            {"speaker": "AGENT", "text": "Your email address is m dot chen at example dot com.", "confidence": 0.95},
            {"speaker": "AGENT", "text": "So look, this all makes sense to you, yeah?", "confidence": 0.93},
            {"speaker": "CUSTOMER", "text": "Uh, yeah, I guess so.", "confidence": 0.9},
            {"speaker": "AGENT", "text": "Great, thanks Michael, that's everything.", "confidence": 0.95},
        ],
        {
            "RECORDING_CONSENT": "PASS",
            "ACCOUNT_HOLDER_CONFIRMED": "PASS",
            "MARKET_OFFER_DISCLOSURE": "PASS",
            "TERMS_ACKNOWLEDGEMENT": "REVIEW",
            "PEAK_RATE_MATCH": "PASS",
            "OFF_PEAK_RATE_MATCH": "PASS",
            "EMAIL_READBACK_MATCH": "PASS",
            "ADDRESS_MATCH": "PASS",
            "PLAN_NAME_MATCH": "PASS",
            "DEAD_AIR": "PASS",
            "CROSSTALK_OR_LOW_CONFIDENCE": "PASS",
        },
    )

    # ---------------------------------------------------------------
    # Lead 3613793 - QA_REVIEW: recording-consent line lands in an OVERLAP
    # (crosstalk) segment, so the guardrail downgrades that critical PASS.
    # ---------------------------------------------------------------
    _add_lead(
        db,
        dict(
            id="3613793",
            retailer="Retailer 1",
            customer_name="Aisha Khan",
            account_holder_name="Aisha Khan",
            email="aisha.khan@example.com",
            address="17 Park Avenue, Bondi NSW 2026",
            plan_id="ENERGY-101",
            call_date=datetime(2026, 9, 8, 14, 0, tzinfo=timezone.utc),
            agent_name="Agent A",
            audio_path="/audio/3613793.mp3",
        ),
        [
            {"speaker": "OVERLAP", "text": "This call is being recorded for quality purposes.", "confidence": 0.70},
            {"speaker": "CUSTOMER", "text": "Sorry, go ahead.", "confidence": 0.85},
            {"speaker": "AGENT", "text": "Can I confirm that I am speaking with Aisha Khan, the account holder?", "confidence": 0.95},
            {"speaker": "CUSTOMER", "text": "Yes, speaking.", "confidence": 0.95},
            {"speaker": "AGENT", "text": "I will now read the required market offer disclosure.", "confidence": 0.95},
            {"speaker": "AGENT", "text": "Your peak electricity rate will be 31.9 cents per kilowatt hour.", "confidence": 0.95},
            {"speaker": "AGENT", "text": "Your off-peak rate will be 21.4 cents per kilowatt hour.", "confidence": 0.95},
            {"speaker": "AGENT", "text": "You will be on our Flexi Saver Plan.", "confidence": 0.95},
            {"speaker": "AGENT", "text": "Can I confirm your address is 17 Park Avenue, Bondi NSW 2026?", "confidence": 0.95},
            {"speaker": "AGENT", "text": "Your email address is aisha dot khan at example dot com.", "confidence": 0.95},
            {"speaker": "AGENT", "text": "Do you understand and accept these terms?", "confidence": 0.95},
            {"speaker": "CUSTOMER", "text": "Yes, I do.", "confidence": 0.95},
            {"speaker": "AGENT", "text": "Thanks Aisha, that's everything.", "confidence": 0.95},
        ],
        {
            "RECORDING_CONSENT": "REVIEW",
            "ACCOUNT_HOLDER_CONFIRMED": "PASS",
            "MARKET_OFFER_DISCLOSURE": "PASS",
            "TERMS_ACKNOWLEDGEMENT": "PASS",
            "PEAK_RATE_MATCH": "PASS",
            "OFF_PEAK_RATE_MATCH": "PASS",
            "EMAIL_READBACK_MATCH": "PASS",
            "ADDRESS_MATCH": "PASS",
            "PLAN_NAME_MATCH": "PASS",
            "DEAD_AIR": "PASS",
            "CROSSTALK_OR_LOW_CONFIDENCE": "FAIL",
        },
    )

    # ---------------------------------------------------------------
    # Lead 3613794 - QA_REVIEW: peak-rate line sits in a low-confidence
    # transcript segment, so the guardrail downgrades that critical PASS.
    # ---------------------------------------------------------------
    _add_lead(
        db,
        dict(
            id="3613794",
            retailer="Retailer 1",
            customer_name="Robert Nguyen",
            account_holder_name="Robert Nguyen",
            email="r.nguyen@example.com",
            address="3 Coral Close, Manly NSW 2095",
            plan_id="ENERGY-101",
            call_date=datetime(2026, 9, 9, 16, 45, tzinfo=timezone.utc),
            agent_name="Agent B",
            audio_path="/audio/3613794.mp3",
        ),
        [
            {"speaker": "AGENT", "text": "This call is being recorded for quality purposes.", "confidence": 0.95},
            {"speaker": "AGENT", "text": "Can I confirm that I am speaking with Robert Nguyen, the account holder?", "confidence": 0.95},
            {"speaker": "CUSTOMER", "text": "Yes.", "confidence": 0.95},
            {"speaker": "AGENT", "text": "I will now read the required market offer disclosure.", "confidence": 0.95},
            {"speaker": "AGENT", "text": "Your peak electricity rate will be 31.9 cents per kilowatt hour.", "confidence": 0.55},
            {"speaker": "AGENT", "text": "Your off-peak rate will be 21.4 cents per kilowatt hour.", "confidence": 0.95},
            {"speaker": "AGENT", "text": "You will be on our Flexi Saver Plan.", "confidence": 0.95},
            {"speaker": "AGENT", "text": "Can I confirm your address is 3 Coral Close, Manly NSW 2095?", "confidence": 0.95},
            {"speaker": "AGENT", "text": "Your email address is r dot nguyen at example dot com.", "confidence": 0.95},
            {"speaker": "AGENT", "text": "Do you understand and accept these terms?", "confidence": 0.95},
            {"speaker": "CUSTOMER", "text": "Yes.", "confidence": 0.95},
            {"speaker": "AGENT", "text": "Thanks Robert, that's everything.", "confidence": 0.95},
        ],
        {
            "RECORDING_CONSENT": "PASS",
            "ACCOUNT_HOLDER_CONFIRMED": "PASS",
            "MARKET_OFFER_DISCLOSURE": "PASS",
            "TERMS_ACKNOWLEDGEMENT": "PASS",
            "PEAK_RATE_MATCH": "REVIEW",
            "OFF_PEAK_RATE_MATCH": "PASS",
            "EMAIL_READBACK_MATCH": "PASS",
            "ADDRESS_MATCH": "PASS",
            "PLAN_NAME_MATCH": "PASS",
            "DEAD_AIR": "PASS",
            "CROSSTALK_OR_LOW_CONFIDENCE": "FAIL",
        },
    )
