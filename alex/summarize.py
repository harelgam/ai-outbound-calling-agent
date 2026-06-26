"""summarize(transcript) -> CallSummary.

A lightweight post-call helper (one Claude call) that turns a raw transcript into
a structured CRM disposition. Mirrors Luna (Harel's AI RevOps) writing the call
back to the CRM. Called by the end-of-call webhook (server.py).
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from . import config
from .prompts import SUMMARY_SYSTEM


class CallSummary(BaseModel):
    outcome: str = Field(
        description="One of: booked, callback, not_interested, voicemail, wrong_person, opt_out."
    )
    meeting_booked: bool = Field(description="True only if a meeting time was confirmed.")
    booked_time: Optional[str] = Field(default=None, description="Confirmed slot label, if any.")
    qualification: Optional[str] = Field(
        default=None, description="Any fit/qualification signal heard."
    )
    referred_to: Optional[str] = Field(
        default=None,
        description="If the wrong person named the right contact, that person's "
        "name (and email/phone if given); otherwise null.",
    )
    objections: list[str] = Field(default_factory=list, description="Objections raised.")
    summary: str = Field(description="2-3 sentence factual recap of the call.")
    next_action: str = Field(description="Recommended next step for the human team.")


def _fallback(transcript: str) -> CallSummary:
    booked = "book" in transcript.lower() and "confirmed" in transcript.lower()
    return CallSummary(
        outcome="booked" if booked else "callback",
        meeting_booked=booked,
        summary="(offline) Transcript captured; run with ANTHROPIC_API_KEY for analysis.",
        next_action="Review transcript manually.",
    )


def summarize(transcript: str) -> CallSummary:
    """Analyze a call transcript into a structured CRM record."""
    if not config.ANTHROPIC_API_KEY:
        return _fallback(transcript)

    import anthropic

    client = anthropic.Anthropic()
    try:
        resp = client.messages.parse(
            model=config.HELPER_MODEL,
            max_tokens=1024,
            system=SUMMARY_SYSTEM,
            messages=[{"role": "user", "content": f"Transcript:\n\n{transcript}"}],
            output_format=CallSummary,
        )
        return resp.parsed_output
    except Exception as e:
        print(f"[summarize] falling back ({e})")
        return _fallback(transcript)
