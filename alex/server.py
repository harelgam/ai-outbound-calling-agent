"""FastAPI webhook server for the live call.

Vapi calls this in two situations during/after a call:
  1. tool-calls       — Alex invoked a tool; we run it and return the result.
  2. end-of-call-report — the call ended; we summarize the transcript -> CRM.

Run locally and expose with ngrok:
    uvicorn alex.server:app --port 8000
    ngrok http 8000   # put the https URL in PUBLIC_WEBHOOK_URL
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import FastAPI, HTTPException, Request

from . import config, crm
from .summarize import summarize
from .tools import BOOKED_STATUSES, execute_tool

app = FastAPI(title="Alex webhook")


def _verify_secret(request: Request) -> None:
    """Reject spoofed webhooks. No-op unless WEBHOOK_SECRET is configured.

    Vapi sends the configured server secret as the `x-vapi-secret` header. We only
    accept the header — not a URL query param — so the secret never lands in
    proxy/access logs. For manual curl testing, pass `-H "x-vapi-secret: ..."`.
    """
    if not config.WEBHOOK_SECRET:
        return
    if request.headers.get("x-vapi-secret") != config.WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="invalid webhook secret")


def _lead_id_from(message: dict[str, Any], body: dict[str, Any]) -> str:
    """Recover the lead id from the call metadata (best-effort across shapes)."""
    for obj in (
        message.get("call", {}),
        message.get("assistant", {}),
        body.get("call", {}),
    ):
        md = (obj or {}).get("metadata") or {}
        if md.get("lead_id"):
            return md["lead_id"]
        overrides = (obj or {}).get("assistantOverrides") or {}
        if (overrides.get("metadata") or {}).get("lead_id"):
            return overrides["metadata"]["lead_id"]
    return "UNKNOWN"


def _handle_tool_calls(message: dict[str, Any], lead_id: str) -> dict[str, Any]:
    """Execute each requested tool and return results in Vapi's expected shape."""
    results = []
    tool_calls = message.get("toolCalls") or message.get("toolCallList") or []
    for call in tool_calls:
        call_id = call.get("id") or call.get("toolCallId")
        fn = call.get("function", {})
        name = fn.get("name")
        raw_args = fn.get("arguments", {})
        args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
        result = execute_tool(name, args, lead_id)
        results.append({"toolCallId": call_id, "result": json.dumps(result)})
    return {"results": results}


def _handle_end_of_call(message: dict[str, Any], lead_id: str) -> dict[str, Any]:
    transcript = message.get("transcript") or ""
    if not transcript and message.get("artifact"):
        transcript = message["artifact"].get("transcript", "")
    summary = summarize(transcript)

    if lead_id == "UNKNOWN":
        print("[end-of-call] no lead id; transcript not attributed")
        return {"received": True}

    # Tool calls made DURING the call are a stronger source of truth than the
    # post-call LLM summary. Never let the summary undo what a tool decided.
    status = (crm.get_lead(lead_id) or {}).get("status")

    if status == "opt_out":
        # DNC is a compliance fact set by the opt_out tool — keep it, summary aside.
        crm.update_lead(lead_id, transcript=transcript)
        print(f"[end-of-call] lead={lead_id} opt_out preserved (summary ignored)")
        return {"received": True}

    if status in BOOKED_STATUSES:
        # Preserve the booking commitment made by book_meeting; don't overwrite it.
        crm.update_lead(
            lead_id,
            disposition="booked",
            transcript=transcript,
            notes=summary.summary,
            next_action=summary.next_action,
            qualification=summary.qualification,
        )
        print(f"[end-of-call] lead={lead_id} booking preserved ({status})")
        return {"received": True}

    # No terminal tool fired: trust the summary, but a "booked" status can ONLY
    # come from the book_meeting tool — downgrade a summary-only "booked".
    outcome = "callback" if summary.outcome == "booked" else summary.outcome
    crm.update_lead(
        lead_id,
        status=outcome,
        disposition=outcome,
        transcript=transcript,
        notes=summary.summary,
        next_action=summary.next_action,
        qualification=summary.qualification,
    )
    print(f"[end-of-call] lead={lead_id} outcome={outcome}")
    return {"received": True}


@app.post("/vapi/webhook")
async def vapi_webhook(request: Request) -> dict[str, Any]:
    _verify_secret(request)
    body = await request.json()
    message = body.get("message", body)
    msg_type = message.get("type")
    lead_id = _lead_id_from(message, body)

    if msg_type in ("tool-calls", "function-call"):
        return _handle_tool_calls(message, lead_id)
    if msg_type == "end-of-call-report":
        return _handle_end_of_call(message, lead_id)
    return {"ignored": msg_type}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
