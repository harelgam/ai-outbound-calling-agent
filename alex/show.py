"""Print the current CRM state (leads + dispositions + bookings)."""
from __future__ import annotations

from . import crm


def main() -> None:
    print("=== Leads ===")
    for lead in crm.list_leads():
        meeting = lead.get("meeting") or {}
        when = f"  @ {meeting['label']}" if meeting.get("label") else ""
        print(
            f"  {lead['lead_id']}  {lead['name']:<14} {lead['company']:<14} "
            f"status={lead['status']:<30} disp={lead.get('disposition')}{when}"
        )
        if meeting.get("attendee_email"):
            print(f"        invite: {meeting['attendee_email']}  meet: {meeting.get('meet_link')}")
            if meeting.get("event_link"):
                print(f"        event: {meeting['event_link']}")
        if lead.get("notes"):
            print(f"        notes: {lead['notes']}")


if __name__ == "__main__":
    main()
