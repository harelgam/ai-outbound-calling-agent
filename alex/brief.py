"""brief(lead) -> CallBrief.

A lightweight pre-call helper (one Claude call) that turns a CRM lead row into a
personalized call brief. This is a supporting module around Alex, not a separate
agent. Mirrors how Katie (Harel's AI SDR) would prep a call.
"""
from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from . import config
from .prompts import BRIEF_SYSTEM


class CallBrief(BaseModel):
    angle: str = Field(description="The single most relevant reason to call this lead.")
    opener: str = Field(description="A natural 1-2 sentence opener, including AI disclosure.")
    talking_points: list[str] = Field(description="2-4 specific, personalized points.")
    likely_objections: list[str] = Field(description="2-3 objections likely from this persona.")


def _fallback(lead: dict[str, Any]) -> CallBrief:
    """Deterministic brief so the demo/eval still runs without an API key."""
    return CallBrief(
        angle=f"{lead['signal']} — Harel's can scale outbound without adding headcount.",
        opener=(
            f"Hi {lead['name'].split()[0]}, this is Alex, an AI calling assistant from Harel's — "
            f"I'll keep it quick. Did I catch you at an okay moment?"
        ),
        talking_points=[
            f"Saw the signal: {lead['signal']}.",
            f"Harel's AI agents handle research and outreach off your CRM data.",
            "Goal is just a 30-minute discovery call with the Harel's team.",
        ],
        likely_objections=["Not interested", "No time right now", "Just send me an email"],
    )


def brief(lead: dict[str, Any]) -> CallBrief:
    """Generate a personalized call brief for a lead (falls back if no API key)."""
    if not config.ANTHROPIC_API_KEY:
        return _fallback(lead)

    import anthropic

    client = anthropic.Anthropic()
    user = (
        "Prepare a call brief for this lead:\n"
        + json.dumps(lead, indent=2)
        + "\n\nHarel's is an AI-native GTM platform whose AI agents automate outbound "
        "(email, LinkedIn, phone) off live CRM data. The ask is a 30-minute intro."
    )
    try:
        resp = client.messages.parse(
            model=config.HELPER_MODEL,
            max_tokens=1024,
            system=BRIEF_SYSTEM,
            messages=[{"role": "user", "content": user}],
            output_format=CallBrief,
        )
        return resp.parsed_output
    except Exception as e:  # never let prep block a call
        print(f"[brief] falling back ({e})")
        return _fallback(lead)
