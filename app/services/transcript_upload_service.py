"""
Parses an uploaded transcript file into a LeadIngestIn payload.

Supported formats

1. Text (.txt) - optional `key: value` header, blank line, then transcript lines:

       lead_id: 3613795
       customer_name: Sam Lee
       ...

       [00:05] AGENT: This call is being recorded for quality purposes.
       [00:11-00:14] CUSTOMER (0.55): Okay, sure.
       AGENT: Lines without a timestamp are laid out automatically.

   Timestamp is `[mm:ss]` or `[mm:ss-mm:ss]`; the optional `(0.55)` after the
   speaker is the transcription confidence (default 0.95). Speakers: AGENT,
   CUSTOMER, UNKNOWN, OVERLAP. Lines starting with `#` are ignored.

2. JSON (.json) - the same shape as the /calls/ingest payload.

Metadata given explicitly (form fields) wins over the file header, which wins
over defaults. Nothing here touches scoring: the parsed transcript is stored
verbatim and scored by the normal deterministic pipeline.
"""
import json
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional

from .. import schemas

SPEAKERS = {"AGENT", "CUSTOMER", "UNKNOWN", "OVERLAP"}
DEFAULT_CONFIDENCE = 0.95
DEFAULT_GAP_SECONDS = 5

REQUIRED_FIELDS = ["customer_name", "email", "address"]

_LINE_RE = re.compile(
    r"^(?:\[(?P<s_min>\d+):(?P<s_sec>\d{2})(?:\s*-\s*(?P<e_min>\d+):(?P<e_sec>\d{2}))?\]\s*)?"
    r"(?P<speaker>[A-Za-z]+)"
    r"(?:\s*\((?P<conf>\d*\.?\d+)\))?"
    r"\s*:\s*(?P<text>\S.*)$"
)
_HEADER_RE = re.compile(r"^([A-Za-z_]+)\s*:\s*(.*)$")


class TranscriptParseError(ValueError):
    pass


def _parse_text(raw: str):
    header: Dict[str, str] = {}
    segments: List[dict] = []
    in_transcript = False
    cursor = 0  # running end time used to lay out untimed lines

    for line_no, line in enumerate(raw.splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        m = _LINE_RE.match(line)
        speaker = m.group("speaker").upper() if m else None
        if m and speaker in SPEAKERS:
            in_transcript = True
            text = m.group("text").strip()
            duration = max(3, len(text) // 12)
            if m.group("s_min") is not None:
                start = int(m.group("s_min")) * 60 + int(m.group("s_sec"))
                if m.group("e_min") is not None:
                    end = int(m.group("e_min")) * 60 + int(m.group("e_sec"))
                else:
                    end = start + duration
            else:
                start = cursor + DEFAULT_GAP_SECONDS
                end = start + duration
            if end < start:
                raise TranscriptParseError(f"Line {line_no}: end time is before start time.")
            conf = float(m.group("conf")) if m.group("conf") else DEFAULT_CONFIDENCE
            if not 0 <= conf <= 1:
                raise TranscriptParseError(f"Line {line_no}: confidence must be between 0 and 1.")
            segments.append(dict(
                speaker=speaker, start_seconds=start, end_seconds=end,
                text=text, transcription_confidence=conf,
            ))
            cursor = end
            continue

        h = _HEADER_RE.match(line)
        if h and not in_transcript:
            header[h.group(1).lower()] = h.group(2).strip()
            continue

        raise TranscriptParseError(
            f"Line {line_no} is not a valid transcript line: expected "
            "'[mm:ss] AGENT: text' or 'AGENT: text'."
        )

    return header, segments


def _parse_datetime(value: str) -> datetime:
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        raise TranscriptParseError(f"call_date '{value}' is not a valid ISO date (e.g. 2026-09-18T10:00:00).")
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def build_ingest_payload(
    filename: str,
    content: bytes,
    overrides: Dict[str, Optional[str]],
) -> schemas.LeadIngestIn:
    try:
        raw = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise TranscriptParseError("File must be UTF-8 text.")

    if filename.lower().endswith(".json"):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise TranscriptParseError(f"Invalid JSON: {exc}")
        if not isinstance(data, dict):
            raise TranscriptParseError("JSON transcript must be an object.")
        header, segments = {k: v for k, v in data.items() if k != "segments"}, data.get("segments", [])
        header = {k: str(v) for k, v in header.items() if v is not None}
    else:
        header, segments = _parse_text(raw)

    if not segments:
        raise TranscriptParseError("No transcript lines found in the file.")

    meta = dict(header)
    meta.update({k: v.strip() for k, v in overrides.items() if v and v.strip()})

    missing = [f for f in REQUIRED_FIELDS if not meta.get(f)]
    if missing:
        raise TranscriptParseError(
            f"Missing required lead details: {', '.join(missing)}. "
            "Fill them in the form or add them as header lines in the file."
        )

    call_date = _parse_datetime(meta["call_date"]) if meta.get("call_date") else datetime.now(timezone.utc)

    try:
        return schemas.LeadIngestIn(
            id=meta.get("lead_id") or meta.get("id") or f"UP{datetime.now(timezone.utc):%y%m%d%H%M%S}",
            retailer=meta.get("retailer") or "Retailer 1",
            customer_name=meta["customer_name"],
            account_holder_name=meta.get("account_holder_name") or meta["customer_name"],
            email=meta["email"],
            address=meta["address"],
            plan_id=meta.get("plan_id") or "ENERGY-101",
            call_date=call_date,
            agent_name=meta.get("agent_name") or "Unknown Agent",
            audio_path=None,
            segments=segments,
        )
    except ValueError as exc:  # pydantic validation of segment fields
        raise TranscriptParseError(f"Invalid transcript data: {exc}")
