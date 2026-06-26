"""Alex's tools — the single source of truth for both call paths.

The same four tools are exposed two ways:
  - to the live Vapi assistant, as Vapi "function" tools that POST to our
    FastAPI webhook (see server.py); and
  - to the local text agent used by the eval harness, as Anthropic tool schemas
    executed in-process (see agent.py).

Both paths ultimately call execute_tool(), so the conversation logic is
identical whether Alex is on a real phone call or in the text simulator.
"""
from __future__ import annotations

import re
from typing import Any

from . import config, crm

# Statuses that mean "a meeting commitment exists" — protected from being
# overwritten by the post-call summary, and reachable only via book_meeting.
BOOKED_STATUSES = {
    "calendar_invite_sent",
    "reserved_pending_calendar_invite",
    "calendar_invite_failed",
}

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def valid_email(email: str | None) -> bool:
    return bool(_EMAIL_RE.match((email or "").strip()))

# --------------------------------------------------------------------------- #
# Tool specs (provider-neutral) — name, description, JSON-schema parameters.
# --------------------------------------------------------------------------- #
TOOL_SPECS: list[dict[str, Any]] = [
    {
        "name": "check_availability",
        "description": (
            "Get open meeting slots for the sales team. Call this when the "
            "prospect shows any interest in talking further, before proposing "
            "specific times."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "count": {
                    "type": "integer",
                    "description": "How many slots to offer (default 2).",
                }
            },
            "required": [],
        },
    },
    {
        "name": "book_meeting",
        "description": (
            "Book the 30-minute discovery call in a specific open slot and send "
            "the calendar invite. Only call this after the prospect has verbally "
            "agreed to a specific time returned by check_availability AND you have "
            "confirmed the email address for the invite."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "slot_iso": {
                    "type": "string",
                    "description": "The exact `iso` value of the chosen slot.",
                },
                "slot_label": {
                    "type": "string",
                    "description": "The human-readable `label` of the chosen slot.",
                },
                "attendee_email": {
                    "type": "string",
                    "description": "The prospect's email for the calendar invite (confirmed on the call).",
                },
            },
            "required": ["slot_iso", "slot_label", "attendee_email"],
        },
    },
    {
        "name": "opt_out",
        "description": (
            "Record a do-not-call request and end the call politely. Call this "
            "IMMEDIATELY if the prospect asks to stop being called, to be "
            "removed, or otherwise withdraws consent."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "reason": {"type": "string", "description": "Brief reason, if given."}
            },
            "required": [],
        },
    },
    {
        "name": "capture_referral",
        "description": (
            "Capture a referral when the person reached is NOT responsible for "
            "pipeline/outreach and names the right contact. Call this BEFORE "
            "log_outcome 'wrong_person' whenever a name is offered, so the right "
            "person becomes a new follow-up lead. Never pressure them to refer."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "referred_name": {
                    "type": "string",
                    "description": "Full name of the right person to contact.",
                },
                "referred_title": {
                    "type": "string",
                    "description": "Their role / title, if mentioned.",
                },
                "referred_email": {
                    "type": "string",
                    "description": "Their email, if given.",
                },
                "referred_phone": {
                    "type": "string",
                    "description": "Their phone in E.164, if given.",
                },
                "notes": {
                    "type": "string",
                    "description": "Any context about the handoff.",
                },
            },
            "required": ["referred_name"],
        },
    },
    {
        "name": "log_outcome",
        "description": (
            "Record the final outcome and end the call. Call this exactly once, "
            "as the last action of every call."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "outcome": {
                    "type": "string",
                    "enum": ["booked", "callback", "not_interested", "voicemail", "wrong_person"],
                    "description": "Final disposition of the call.",
                },
                "notes": {
                    "type": "string",
                    "description": "One-line summary of what happened / qualification signal.",
                },
            },
            "required": ["outcome"],
        },
    },
]

TERMINAL_TOOLS = {"opt_out", "log_outcome"}
_SPEC_BY_NAME = {s["name"]: s for s in TOOL_SPECS}


# --------------------------------------------------------------------------- #
# Execution — called by both the webhook server and the local agent.
# --------------------------------------------------------------------------- #
_VALID_OUTCOMES = {"booked", "callback", "not_interested", "voicemail", "wrong_person"}


def execute_tool(name: str, args: dict[str, Any], lead_id: str) -> dict[str, Any]:
    """Run a tool against the mock CRM/calendar and return a JSON-able result.

    Inputs come from a live LLM over a phone call, so they can be missing or
    malformed. This function validates args and never raises — it returns an
    `{"error": ...}` result the agent can read and recover from instead of
    crashing the webhook.
    """
    try:
        args = args or {}

        if crm.get_lead(lead_id) is None:
            return {"error": f"unknown lead_id '{lead_id}'"}

        if name == "check_availability":
            try:
                count = int(args.get("count", 2))
            except (TypeError, ValueError):
                count = 2
            count = max(1, min(count, 5))
            return {"slots": crm.open_slots(count)}

        if name == "book_meeting":
            return _book_meeting(args, lead_id)

        if name == "capture_referral":
            return _capture_referral(args, lead_id)

        if name == "opt_out":
            crm.update_lead(lead_id, status="opt_out", disposition="opt_out", notes=args.get("reason"))
            return {"acknowledged": True}

        if name == "log_outcome":
            outcome = args.get("outcome")
            if outcome not in _VALID_OUTCOMES:
                return {"error": f"outcome must be one of {sorted(_VALID_OUTCOMES)}"}
            # Don't downgrade an existing booking commitment to a generic outcome.
            current = (crm.get_lead(lead_id) or {}).get("status")
            status = current if current in BOOKED_STATUSES else outcome
            crm.update_lead(lead_id, status=status, disposition=outcome, notes=args.get("notes"))
            return {"acknowledged": True, "outcome": outcome}

        return {"error": f"unknown tool '{name}'"}
    except Exception as e:  # never let a tool crash the call/webhook
        return {"error": f"tool '{name}' failed: {e}"}


def _capture_referral(args: dict[str, Any], lead_id: str) -> dict[str, Any]:
    """Turn a 'wrong person — talk to X' moment into a new follow-up lead.

    Creates a CRM lead for the referred contact (inheriting the company from the
    source lead) and links it back to the source. NOT a terminal tool: the call
    continues, and Alex still logs the source lead as `wrong_person`.
    """
    referred_name = (args.get("referred_name") or "").strip()
    if not referred_name:
        return {"captured": False, "error": "referred_name is required"}

    source = crm.get_lead(lead_id) or {}
    source_name = source.get("name") or lead_id

    email = (args.get("referred_email") or "").strip()
    email_invalid = bool(email) and not valid_email(email)
    if email_invalid:
        email = ""  # capture the lead anyway, just without a bad address

    new_lead = crm.add_lead(
        name=referred_name,
        email=email,
        phone=(args.get("referred_phone") or "").strip(),
        title=(args.get("referred_title") or "").strip(),
        company=source.get("company", ""),
        industry=source.get("industry", ""),
        employees=source.get("employees", 0) or 0,
        signal=(
            f"Referred by {source_name} at {source.get('company') or 'their company'} "
            "during an outbound call."
        ),
    )
    new_id = new_lead["lead_id"]
    crm.update_lead(
        new_id,
        next_action=f"Follow up — referred by {source_name} ({lead_id}).",
        notes=(args.get("notes") or "").strip() or None,
    )
    # Record the handoff on the source lead so it's visible in the CRM.
    crm.update_lead(
        lead_id,
        referred_to={"lead_id": new_id, "name": referred_name},
        next_action=f"Referred to {referred_name} ({new_id}).",
    )
    result: dict[str, Any] = {
        "captured": True,
        "new_lead_id": new_id,
        "referred_name": referred_name,
    }
    if email_invalid:
        result["warning"] = "referred_email was not a valid address and was dropped"
    return result


def _book_meeting(args: dict[str, Any], lead_id: str) -> dict[str, Any]:
    """Book the 30-min discovery call: validate email, reserve slot, send invite.

    Tool-truth discipline: never report `booked: True` with a sent invite unless a
    real calendar event was created. On calendar failure, the slot stays reserved
    and the lead is flagged for manual follow-up.
    """
    slot_iso = args.get("slot_iso")
    if not slot_iso:
        return {"booked": False, "error": "slot_iso is required (use a value from check_availability)"}

    attendee_email = (args.get("attendee_email") or "").strip()
    if not valid_email(attendee_email):
        return {
            "booked": False,
            "error": "a valid attendee_email is required — confirm the prospect's email first",
        }

    res = crm.reserve(lead_id, slot_iso)
    if not res.get("ok"):
        return {"booked": False, "reason": res.get("reason", "unknown")}

    slot_label = args.get("slot_label") or slot_iso
    meeting: dict[str, Any] = {
        "iso": slot_iso,
        "label": slot_label,
        "attendee_email": attendee_email,
        "organizer_email": config.SALES_TEAM_EMAIL,
    }

    if not config.GCAL_ENABLED:
        # Mock booking: slot reserved, invite to be sent manually by the team.
        crm.update_lead(
            lead_id,
            status="reserved_pending_calendar_invite",
            disposition="booked",
            meeting=meeting,
        )
        return {
            "booked": True,
            "status": "reserved_pending_calendar_invite",
            "attendee_email": attendee_email,
            "slot": slot_label,
        }

    from .google_calendar import create_event

    gres = create_event(slot_iso, attendee_email)
    if not gres.get("ok"):
        # Honest failure: don't claim an invite was sent. Keep the slot reserved.
        crm.update_lead(
            lead_id, status="calendar_invite_failed", disposition="booked", meeting=meeting
        )
        return {
            "booked": False,
            "error": f"calendar invite failed: {gres.get('error')}",
            "manual_follow_up": True,
            "attendee_email": attendee_email,
        }

    meeting.update(
        event_id=gres.get("event_id"),
        event_link=gres.get("event_link"),
        meet_link=gres.get("meet_link"),
    )
    crm.update_lead(
        lead_id, status="calendar_invite_sent", disposition="booked", meeting=meeting
    )
    return {
        "booked": True,
        "status": "calendar_invite_sent",
        "attendee_email": attendee_email,
        "meet_link": gres.get("meet_link"),
        "slot": slot_label,
    }


# --------------------------------------------------------------------------- #
# Schema adapters
# --------------------------------------------------------------------------- #
def anthropic_tools() -> list[dict[str, Any]]:
    """Anthropic Messages API tool definitions."""
    return [
        {"name": s["name"], "description": s["description"], "input_schema": s["parameters"]}
        for s in TOOL_SPECS
    ]


def vapi_tools(server_url: str, secret: str = "") -> list[dict[str, Any]]:
    """Vapi 'function' tool definitions that call back into our webhook."""
    server: dict[str, Any] = {"url": server_url}
    if secret:
        server["secret"] = secret  # sent back as the x-vapi-secret header
    return [
        {
            "type": "function",
            "function": {
                "name": s["name"],
                "description": s["description"],
                "parameters": s["parameters"],
            },
            "server": dict(server),
        }
        for s in TOOL_SPECS
    ]
