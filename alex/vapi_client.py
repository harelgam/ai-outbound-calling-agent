"""Vapi integration: build Alex's assistant config and place outbound calls.

Vapi is the managed voice platform — it runs the realtime STT -> Claude -> TTS
loop and calls our webhook (server.py) for tools and the end-of-call report.

NOTE: Vapi's API shapes evolve; the payloads below match Vapi's documented
assistant/call schema at time of writing. If a field is rejected, check the
current Vapi docs — the structure (model/voice/transcriber/tools/server) is
stable even if a key name shifts.
"""
from __future__ import annotations

from typing import Any, Optional

import requests

from . import config
from .brief import CallBrief
from .prompts import ALEX_SYSTEM, call_context_block
from .tools import vapi_tools


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {config.VAPI_API_KEY}", "Content-Type": "application/json"}


def _webhook_url() -> str:
    return f"{config.PUBLIC_WEBHOOK_URL}/vapi/webhook"


def _server_config() -> dict[str, Any]:
    server: dict[str, Any] = {"url": _webhook_url()}
    if config.WEBHOOK_SECRET:
        server["secret"] = config.WEBHOOK_SECRET
    return server


def build_assistant(system_prompt: str) -> dict[str, Any]:
    """Assistant config: Claude as the brain, our tools, our webhook."""
    return {
        "name": "Alex (Harel's AI Calling Agent)",
        "firstMessageMode": "assistant-speaks-first",
        "model": {
            "provider": "anthropic",
            "model": config.CALLER_MODEL,
            "messages": [{"role": "system", "content": system_prompt}],
            # Our function tools + Vapi's built-in endCall so Alex can hang up.
            "tools": vapi_tools(_webhook_url(), config.WEBHOOK_SECRET) + [{"type": "endCall"}],
        },
        "voice": config.VAPI_VOICE,
        "transcriber": config.VAPI_TRANSCRIBER,
        # Receive tool calls + the end-of-call report at our webhook. When a secret
        # is configured, Vapi sends it back as the `x-vapi-secret` header.
        "server": _server_config(),
        "serverMessages": ["tool-calls", "end-of-call-report", "status-update"],
        # Leave a voicemail instead of hanging up on machines.
        "voicemailDetection": {"provider": "vapi"},
        # Let Alex end the call himself; also auto-hang-up when he signs off.
        "endCallFunctionEnabled": True,
        "endCallPhrases": [
            "goodbye", "good bye", "bye now", "have a great day",
            "have a good one", "take care", "talk soon",
        ],
        "metadata": {"app": "alex-demo"},
    }


def place_call(lead: dict[str, Any], brief: CallBrief, to_number: str) -> dict[str, Any]:
    """Place a single outbound call to `to_number`, personalized for `lead`.

    Uses an inline transient assistant so the per-call system prompt (base +
    lead context + brief) is baked in without managing assistant versions.
    """
    if not (config.VAPI_API_KEY and config.VAPI_PHONE_NUMBER_ID and config.PUBLIC_WEBHOOK_URL):
        raise RuntimeError(
            "Set VAPI_API_KEY, VAPI_PHONE_NUMBER_ID and PUBLIC_WEBHOOK_URL in .env"
        )

    system_prompt = ALEX_SYSTEM + "\n" + call_context_block(lead, brief)
    payload: dict[str, Any] = {
        "phoneNumberId": config.VAPI_PHONE_NUMBER_ID,
        "customer": {"number": to_number},
        # Carry the lead id so the webhook can attribute tool calls + the report.
        "assistant": build_assistant(system_prompt),
        "assistantOverrides": {"metadata": {"lead_id": lead["lead_id"]}},
        "metadata": {"lead_id": lead["lead_id"]},
    }
    resp = requests.post(f"{config.VAPI_BASE_URL}/call", headers=_headers(), json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()


def get_call(call_id: str) -> dict[str, Any]:
    resp = requests.get(
        f"{config.VAPI_BASE_URL}/call/{call_id}", headers=_headers(), timeout=30
    )
    resp.raise_for_status()
    return resp.json()
