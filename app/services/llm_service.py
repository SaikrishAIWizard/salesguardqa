"""
LLM adapter interface for optional semantic fallback checks.

The application must work fully without an API key. When no key is
configured, `is_available()` returns False and every caller falls back to
deterministic Python logic (returning REVIEW on uncertainty).

The LLM is NEVER used to:
  - modify transcript text, CRM data, plan data, or rule data
  - decide factual equality (rates, emails, addresses) - that is deterministic
  - change the deterministic gate decision

It is only used for:
  - semantic/paraphrase judgement on SCRIPT rules when Python matching is
    uncertain
  - optional non-critical behaviour notes (frustration, unclear objection
    handling, etc.)
"""
import os
import json
from typing import Optional, Tuple

_client = None
_checked = False
MODEL = os.environ.get("OPENAI_MODEL") or "gpt-4o-mini"


def is_available() -> bool:
    global _client, _checked
    if _checked:
        return _client is not None
    _checked = True
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        _client = None
        return False
    try:
        import openai  # type: ignore
        _client = openai.OpenAI(api_key=api_key)
        return True
    except Exception:
        _client = None
        return False


def semantic_script_check(rule_name: str, rule_description: str, agent_text: str) -> Optional[Tuple[str, float]]:
    """
    Ask the LLM whether the agent's spoken words fulfil the intent of a
    compliance rule. Returns (verdict, confidence) where verdict is one of
    "FULFILLS" / "DOES_NOT_FULFILL" / "UNCLEAR", or None if the LLM is
    unavailable or the call fails for any reason (caller must treat that as
    REVIEW, never as a silent pass/fail).
    """
    if not is_available():
        return None
    try:
        prompt = (
            "You are assisting a compliance QA system for regulated phone sales. "
            "You NEVER rewrite transcripts and NEVER decide the final gate outcome - "
            "you only judge whether spoken wording fulfils a rule's intent.\n\n"
            f"Rule: {rule_name}\n"
            f"Rule intent: {rule_description}\n\n"
            f"What the agent actually said (verbatim transcript excerpt):\n\"\"\"\n{agent_text}\n\"\"\"\n\n"
            "Respond with ONLY a JSON object of the form "
            '{"verdict": "FULFILLS"|"DOES_NOT_FULFILL"|"UNCLEAR", "confidence": <0..1>}. '
            "Use UNCLEAR with low confidence whenever the wording is ambiguous."
        )
        resp = _client.chat.completions.create(
            model=MODEL,
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        text = (resp.choices[0].message.content or "").strip()
        start = text.find("{")
        end = text.rfind("}")
        data = json.loads(text[start:end + 1])
        verdict = data.get("verdict", "UNCLEAR")
        confidence = float(data.get("confidence", 0.0))
        return verdict, confidence
    except Exception:
        return None


def behaviour_note(agent_text: str, customer_text: str) -> Optional[str]:
    """Optional non-critical LLM observation. Never produces a critical failure."""
    if not is_available():
        return None
    try:
        prompt = (
            "Read this sales call transcript excerpt and, in one short sentence, note any "
            "coaching-worthy behaviour signal such as frustration, interruption, or unclear "
            "objection handling. If nothing stands out, respond with exactly: NONE.\n\n"
            f"Agent: {agent_text}\nCustomer: {customer_text}"
        )
        resp = _client.chat.completions.create(
            model=MODEL,
            max_tokens=100,
            messages=[{"role": "user", "content": prompt}],
        )
        text = (resp.choices[0].message.content or "").strip()
        if text.upper() == "NONE" or not text:
            return None
        return text
    except Exception:
        return None
