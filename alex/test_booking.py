"""Manual booking smoke test — run BEFORE a Vapi call.

Verifies the booking half works on its own: check_availability -> pick a slot ->
book_meeting (and, when GCAL_ENABLED=true, a real Google Calendar invite). No
phone, no Vapi — it drives the exact same tool path Alex uses on a call.

    python -m alex.test_booking --lead L001 --email you@example.com

With GCAL_ENABLED=false (default) it confirms a mock reservation; with
GCAL_ENABLED=true it sends a real invite to --email (check that inbox).
"""
from __future__ import annotations

import argparse
import json

from . import config, crm
from .tools import execute_tool, valid_email


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test the booking flow (no Vapi).")
    parser.add_argument("--lead", default="L001", help="Lead id from leads.csv")
    parser.add_argument(
        "--email",
        default=config.SALES_TEAM_EMAIL,
        help="attendee email for the invite (use your own to actually receive it)",
    )
    args = parser.parse_args()

    lead = crm.get_lead(args.lead)
    if not lead:
        print(f"No such lead: {args.lead}. Available: {[l['lead_id'] for l in crm.list_leads()]}")
        return 1
    if not valid_email(args.email):
        print(f"Invalid email: {args.email}")
        return 1

    print(f"Lead:     {lead['name']} ({lead['company']})")
    print(f"GCAL_ENABLED={config.GCAL_ENABLED}   attendee={args.email}\n")

    slots = execute_tool("check_availability", {"count": 2}, lead["lead_id"]).get("slots", [])
    if not slots:
        print("No open slots available.")
        return 1
    chosen = slots[0]
    print(f"check_availability -> {[s['label'] for s in slots]}")
    print(f"picking            -> {chosen['label']}\n")

    result = execute_tool(
        "book_meeting",
        {"slot_iso": chosen["iso"], "slot_label": chosen["label"], "attendee_email": args.email},
        lead["lead_id"],
    )
    print("book_meeting result:")
    print(json.dumps(result, indent=2))

    refreshed = crm.get_lead(lead["lead_id"])
    print("\nCRM meeting record:")
    print(json.dumps(refreshed.get("meeting"), indent=2))
    print(f"\nlead status: {refreshed['status']}")

    if result.get("booked") and result.get("status") == "calendar_invite_sent":
        print(f"\n[OK] Real invite sent — check {args.email}" + (
            f"  (Meet: {result.get('meet_link')})" if result.get("meet_link") else ""
        ))
        return 0
    if result.get("booked"):
        print("\n[OK] Mock booking succeeded (set GCAL_ENABLED=true for a real invite).")
        return 0
    print("\n[FAIL] Booking did not succeed — see error above.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
