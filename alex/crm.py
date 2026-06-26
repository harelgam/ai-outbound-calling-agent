"""Mock CRM + calendar.

Stands in for Salesforce/HubSpot (leads + dispositions) and Cal.com/Google
Calendar (availability + bookings). Backed by a single JSON file so the demo is
inspectable and has zero external dependencies. Seeded from leads.csv.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import threading
from typing import Any, Optional

from . import config

_LOCK = threading.Lock()


# --------------------------------------------------------------------------- #
# Store load / save
# --------------------------------------------------------------------------- #
def _seed_from_csv() -> dict[str, Any]:
    leads: dict[str, Any] = {}
    with open(config.LEADS_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            row["employees"] = int(row["employees"])
            row["email"] = (row.get("email") or "").strip() or None  # optional prospect email
            row["phone"] = (row.get("phone") or "").strip() or None  # E.164, for outbound call
            row["status"] = "new"          # new | reserved_pending_calendar_invite |
                                            # calendar_invite_sent | calendar_invite_failed |
                                            # callback | not_interested | opt_out
            row["disposition"] = None      # filled by summarize()
            row["meeting"] = None          # booked slot + invite details
            row["transcript"] = None
            row["notes"] = None            # call summary text
            row["next_action"] = None      # recommended next step
            row["qualification"] = None    # qualification signal heard
            leads[row["lead_id"]] = row
    return {"leads": leads, "bookings": []}


def _load() -> dict[str, Any]:
    if config.CRM_STORE.exists():
        return json.loads(config.CRM_STORE.read_text(encoding="utf-8"))
    store = _seed_from_csv()
    _save(store)
    return store


def _save(store: dict[str, Any]) -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.CRM_STORE.write_text(json.dumps(store, indent=2), encoding="utf-8")


def reset() -> None:
    """Re-seed the store from leads.csv (used by tests and fresh demos)."""
    with _LOCK:
        _save(_seed_from_csv())


# --------------------------------------------------------------------------- #
# Leads
# --------------------------------------------------------------------------- #
def get_lead(lead_id: str) -> Optional[dict[str, Any]]:
    return _load()["leads"].get(lead_id)


def list_leads(status: Optional[str] = None) -> list[dict[str, Any]]:
    leads = list(_load()["leads"].values())
    return [l for l in leads if status is None or l["status"] == status]


def update_lead(lead_id: str, **fields: Any) -> dict[str, Any]:
    with _LOCK:
        store = _load()
        lead = store["leads"][lead_id]
        lead.update(fields)
        _save(store)
        return lead


# Call-state fields cleared by reset_lead (identity fields are preserved).
_CALL_STATE = {
    "status": "new",
    "disposition": None,
    "meeting": None,
    "transcript": None,
    "notes": None,
    "next_action": None,
    "qualification": None,
}


def _next_id(store: dict[str, Any]) -> str:
    nums = [int(k[1:]) for k in store["leads"] if k[1:].isdigit()]
    return "L%03d" % ((max(nums) + 1) if nums else 1)


def add_lead(
    name: str,
    email: str = "",
    phone: str = "",
    title: str = "",
    company: str = "",
    industry: str = "",
    employees: int = 0,
    signal: str = "",
) -> dict[str, Any]:
    """Add a new customer to the CRM and return it."""
    with _LOCK:
        store = _load()
        lid = _next_id(store)
        lead = {
            "lead_id": lid,
            "name": name,
            "title": title,
            "company": company,
            "industry": industry,
            "employees": int(employees or 0),
            "signal": signal,
            "email": (email or "").strip() or None,
            "phone": (phone or "").strip() or None,
            **_CALL_STATE,
        }
        store["leads"][lid] = lead
        _save(store)
        return lead


def delete_lead(lead_id: str) -> bool:
    """Remove a customer and free any slot they had reserved. Returns True if it existed."""
    with _LOCK:
        store = _load()
        existed = store["leads"].pop(lead_id, None) is not None
        store["bookings"] = [b for b in store["bookings"] if b.get("lead_id") != lead_id]
        _save(store)
        return existed


def reset_lead(lead_id: str) -> Optional[dict[str, Any]]:
    """Clear one customer's call result (status/meeting/transcript/summary) and free
    their reserved slot, keeping their identity. Lets you re-demo calling the same lead."""
    with _LOCK:
        store = _load()
        lead = store["leads"].get(lead_id)
        if lead is None:
            return None
        store["bookings"] = [b for b in store["bookings"] if b.get("lead_id") != lead_id]
        lead.update(_CALL_STATE)
        _save(store)
        return lead


# --------------------------------------------------------------------------- #
# Calendar
# --------------------------------------------------------------------------- #
def open_slots(num: int = 3) -> list[dict[str, str]]:
    """Next `num` business-day slots at 10:00 and 14:00 (America/New_York-ish).

    Returns a list of {id, label, iso}. Already-booked ISO times are excluded.
    """
    booked = {b["iso"] for b in _load()["bookings"]}
    slots: list[dict[str, str]] = []
    day = dt.date.today()
    while len(slots) < num:
        day += dt.timedelta(days=1)
        if day.weekday() >= 5:  # skip Sat/Sun
            continue
        for hour in (10, 14):
            when = dt.datetime.combine(day, dt.time(hour))
            iso = when.isoformat(timespec="minutes")
            if iso in booked:
                continue
            # Cross-platform 12-hour label (avoid %-I, which is glibc-only).
            hour12 = hour % 12 or 12
            ampm = "AM" if hour < 12 else "PM"
            label = f"{when.strftime('%A %b %d')} at {hour12}:00 {ampm} {config.SLOT_TZ_LABEL}"
            slots.append({"id": f"S-{iso}", "label": label, "iso": iso})
            if len(slots) >= num:
                break
    return slots


def reserve(lead_id: str, slot_iso: str) -> dict[str, Any]:
    """Hold a calendar slot so it can't be double-booked.

    Reserving the slot is separate from writing the lead's meeting/status — the
    caller (tools.book_meeting) decides the final status based on whether a real
    calendar invite was sent.
    """
    with _LOCK:
        store = _load()
        if any(b["iso"] == slot_iso for b in store["bookings"]):
            return {"ok": False, "reason": "slot_taken"}
        store["bookings"].append({"lead_id": lead_id, "iso": slot_iso})
        _save(store)
        return {"ok": True}


def release(slot_iso: str) -> None:
    """Free a previously reserved slot (e.g. if booking is abandoned)."""
    with _LOCK:
        store = _load()
        store["bookings"] = [b for b in store["bookings"] if b["iso"] != slot_iso]
        _save(store)
