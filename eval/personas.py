"""Simulated prospect personas + a Claude-backed prospect role-player.

Each persona pairs a lead (from the CRM) with a behavior profile and the outcome
we expect a good agent to reach. The eval runs Alex's real prompt+tools against
these in text.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from alex import config


@dataclass
class Persona:
    key: str
    lead_id: str
    description: str
    system: str
    expected_outcome: str  # "booked" | "opt_out" | "not_interested_or_callback"


PERSONAS: list[Persona] = [
    Persona(
        key="interested",
        lead_id="L001",
        description="Warm, has the hiring-SDRs pain, willing to book.",
        expected_outcome="booked",
        system=(
            "You are role-playing a B2B prospect: a VP of Sales who is genuinely "
            "stretched because you're hiring SDRs. You're a bit skeptical at first "
            "but open. If the caller is clear and relevant, you agree to a short "
            "intro meeting and pick one of the times they offer. Keep replies to "
            "1-2 short, natural spoken sentences."
        ),
    ),
    Persona(
        key="busy",
        lead_id="L002",
        description="Pressed for time; pushes back before maybe agreeing.",
        expected_outcome="booked",
        system=(
            "You are role-playing a busy Head of Growth. You open with 'I've only "
            "got a minute' and push back once or twice (no time, send an email). "
            "If the caller is concise and offers a specific short slot, you'll book "
            "it. Keep replies to 1-2 short, natural spoken sentences."
        ),
    ),
    Persona(
        key="hostile_optout",
        lead_id="L004",
        description="Annoyed by cold calls; demands to be removed.",
        expected_outcome="opt_out",
        system=(
            "You are role-playing an irritated founder who hates cold calls. "
            "Within your first or second reply, firmly say you're not interested, "
            "to take you off the list, and to never call again. Do NOT agree to "
            "anything. Keep replies to 1-2 short, blunt spoken sentences."
        ),
    ),
]


class SimulatedProspect:
    """Role-plays one persona over a conversation, one reply at a time."""

    def __init__(self, persona: Persona):
        self.persona = persona
        self._messages: list[dict[str, str]] = []
        self._client = None
        if config.ANTHROPIC_API_KEY:
            import anthropic

            self._client = anthropic.Anthropic()

    def respond(self, alex_line: str) -> str:
        # Alex's utterance is the "user" turn from the prospect's perspective.
        self._messages.append({"role": "user", "content": alex_line or "(silence)"})
        if self._client is None:
            return self._fallback()
        resp = self._client.messages.create(
            model=config.PROSPECT_MODEL,
            max_tokens=150,
            system=self.persona.system
            + "\nYou are on a phone call. Never break character or mention you are an AI.",
            messages=self._messages,
        )
        text = " ".join(b.text for b in resp.content if b.type == "text").strip()
        self._messages.append({"role": "assistant", "content": text})
        return text

    def _fallback(self) -> str:
        # Deterministic scripted replies so the harness runs without an API key.
        scripts = {
            "interested": ["Okay, I have a minute.", "Sure, Tuesday works.", "Sounds good, thanks."],
            "busy": ["I've only got a minute.", "Just send me an email.", "Fine, book the short one."],
            "hostile_optout": ["Not interested — take me off your list.", "Don't call me again."],
        }
        turn = sum(1 for m in self._messages if m["role"] == "user") - 1
        seq = scripts[self.persona.key]
        reply = seq[min(turn, len(seq) - 1)]
        self._messages.append({"role": "assistant", "content": reply})
        return reply
