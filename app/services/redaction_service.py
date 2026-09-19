"""
Redacts card-number-like sequences before transcript text is ever returned
by the API or rendered in the UI. Applied at the API boundary, not stored
destructively in the database, so the raw text never leaks unredacted.
"""
import re

# 16-digit sequences, optionally grouped in 4s with spaces or dashes.
# The trailing `\d` (rather than allowing the group to end on a separator)
# keeps the match from swallowing a following space into the redaction.
_CARD_PATTERN = re.compile(r"\b(?:\d[ -]?){12,18}\d\b")


def _looks_like_card(match: str) -> bool:
    digits = re.sub(r"[ -]", "", match)
    return digits.isdigit() and 13 <= len(digits) <= 19


def redact_card_numbers(text: str) -> str:
    if not text:
        return text

    def _replace(m: re.Match) -> str:
        if _looks_like_card(m.group(0)):
            return "[REDACTED CARD NUMBER]"
        return m.group(0)

    return _CARD_PATTERN.sub(_replace, text)
