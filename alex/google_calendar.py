"""Minimal Google Calendar integration behind the book_meeting tool.

Lazily imports the Google client libraries so the rest of the project (and the
test suite) runs without them when GCAL_ENABLED is false. Creating an event:

    create_event(slot_iso, attendee_email) -> {ok, event_id, event_link, meet_link}
                                           or {ok: False, error}

First-time auth: `python -m alex.google_calendar_auth` (see google_calendar_auth.py).
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from . import config

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]


def _service():
    """Build an authorized Calendar API client from the stored token."""
    from google.auth.transport.requests import Request as GoogleRequest
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    from pathlib import Path

    if not Path(config.GCAL_TOKEN_PATH).exists():
        raise RuntimeError(
            f"No Google token at {config.GCAL_TOKEN_PATH}. "
            "Run: python -m alex.google_calendar_auth"
        )
    creds = Credentials.from_authorized_user_file(config.GCAL_TOKEN_PATH, SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(GoogleRequest())
        else:
            raise RuntimeError(
                "Google token invalid/expired. Re-run: python -m alex.google_calendar_auth"
            )
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def create_event(slot_iso: str, attendee_email: str) -> dict[str, Any]:
    """Create a 30-minute discovery call, invite the prospect + sales team.

    Returns a structured result; never raises (so a calendar failure can be
    reported honestly rather than crashing the call).
    """
    try:
        start = dt.datetime.fromisoformat(slot_iso)
        end = start + dt.timedelta(minutes=config.MEETING_MINUTES)
        body: dict[str, Any] = {
            "summary": "Harel's — 30-min Discovery Call",
            "description": (
                "30-minute remote discovery call with Harel's sales team. "
            ),
            "start": {"dateTime": start.isoformat(), "timeZone": config.SLOT_IANA_TZ},
            "end": {"dateTime": end.isoformat(), "timeZone": config.SLOT_IANA_TZ},
            # The event is created on the authenticated calendar (GCAL_CALENDAR_ID,
            # default "primary"), so that account is automatically the organizer and
            # attendee — we don't re-add it, and `attendees[].organizer` is read-only
            # (ignored on insert). If SALES_TEAM_EMAIL is a *different* account than
            # the one that authorized the token, add it here so that person is invited.
            "attendees": [
                {"email": attendee_email},
            ],
        }
        insert_kwargs: dict[str, Any] = {
            "calendarId": config.GCAL_CALENDAR_ID,
            "body": body,
            "sendUpdates": "all",
        }
        if config.GCAL_CREATE_MEET:
            body["conferenceData"] = {
                "createRequest": {
                    "requestId": f"harels-{slot_iso}",
                    "conferenceSolutionKey": {"type": "hangoutsMeet"},
                }
            }
            insert_kwargs["conferenceDataVersion"] = 1

        event = _service().events().insert(**insert_kwargs).execute()

        meet_link = None
        for ep in (event.get("conferenceData") or {}).get("entryPoints", []):
            if ep.get("entryPointType") == "video":
                meet_link = ep.get("uri")
                break

        return {
            "ok": True,
            "event_id": event.get("id"),
            "event_link": event.get("htmlLink"),
            "meet_link": meet_link,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}
