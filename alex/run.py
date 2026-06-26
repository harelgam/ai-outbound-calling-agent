"""Campaign runner — the live demo entry point.

    python -m alex.run --lead L001 --to +14155550123

Flow: load lead -> brief() -> place the outbound call via Vapi. Alex runs the
conversation on the phone; tool calls and the end-of-call summary are handled by
the webhook server (alex/server.py), which writes the outcome back to the CRM.

Inspect results afterwards with:  python -m alex.show
"""
from __future__ import annotations

import argparse
import sys

from . import config, crm
from .brief import brief
from .vapi_client import place_call


def main() -> int:
    parser = argparse.ArgumentParser(description="Place an outbound call as Alex.")
    parser.add_argument("--lead", default="L001", help="Lead id from leads.csv (default L001)")
    parser.add_argument("--to", default=config.DEMO_CALL_NUMBER, help="Number to call (E.164)")
    args = parser.parse_args()

    lead = crm.get_lead(args.lead)
    if not lead:
        print(f"No such lead: {args.lead}. Available: {[l['lead_id'] for l in crm.list_leads()]}")
        return 1
    if not args.to:
        print("No destination number. Pass --to +1... or set DEMO_CALL_NUMBER in .env")
        return 1

    print(f"Preparing call to {lead['name']} ({lead['company']})...")
    call_brief = brief(lead)
    print(f"  angle: {call_brief.angle}")
    print(f"  opener: {call_brief.opener}\n")

    print(f"Placing call to {args.to} via Vapi...")
    call = place_call(lead, call_brief, args.to)
    print(f"  call id: {call.get('id')}  status: {call.get('status')}")
    print("\nAnswer your phone. After the call, the webhook will write the outcome to the CRM.")
    print("View it with:  python -m alex.show")
    return 0


if __name__ == "__main__":
    sys.exit(main())
