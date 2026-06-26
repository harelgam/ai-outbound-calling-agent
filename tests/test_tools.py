"""Unit tests for the tool layer (CRM + calendar + tool dispatch).

These run with no API key and no network — they exercise the deterministic
business logic that both the live call and the eval depend on.
"""
from __future__ import annotations

import pytest

from alex import config, crm
from alex.tools import TOOL_SPECS, anthropic_tools, execute_tool, valid_email, vapi_tools

EMAIL = "buyer@example.com"


def _book_first_slot(lead_id, email=EMAIL):
    slot = execute_tool("check_availability", {"count": 1}, lead_id)["slots"][0]
    return slot, execute_tool(
        "book_meeting",
        {"slot_iso": slot["iso"], "slot_label": slot["label"], "attendee_email": email},
        lead_id,
    )


@pytest.fixture(autouse=True)
def fresh_crm():
    crm.reset()
    yield
    crm.reset()


def test_leads_seeded():
    leads = crm.list_leads()
    assert len(leads) >= 5
    assert all(l["status"] == "new" for l in leads)


def test_check_availability_returns_slots():
    result = execute_tool("check_availability", {"count": 2}, "L001")
    assert len(result["slots"]) == 2
    assert all({"id", "label", "iso"} <= set(s) for s in result["slots"])


def test_book_meeting_mock_reserves_pending_invite(monkeypatch):
    monkeypatch.setattr(config, "GCAL_ENABLED", False)
    slot, result = _book_first_slot("L001")
    assert result["booked"] is True
    assert result["status"] == "reserved_pending_calendar_invite"
    lead = crm.get_lead("L001")
    assert lead["status"] == "reserved_pending_calendar_invite"
    assert lead["meeting"]["iso"] == slot["iso"]
    assert lead["meeting"]["attendee_email"] == EMAIL
    assert lead["meeting"]["organizer_email"] == config.SALES_TEAM_EMAIL


def test_book_meeting_requires_valid_email():
    slot = execute_tool("check_availability", {"count": 1}, "L001")["slots"][0]
    missing = execute_tool("book_meeting", {"slot_iso": slot["iso"], "slot_label": slot["label"]}, "L001")
    assert missing["booked"] is False and "error" in missing
    bad = execute_tool(
        "book_meeting",
        {"slot_iso": slot["iso"], "slot_label": slot["label"], "attendee_email": "not-an-email"},
        "L001",
    )
    assert bad["booked"] is False and "error" in bad
    assert crm.get_lead("L001")["status"] == "new"  # nothing reserved on invalid email


def test_valid_email_helper():
    assert valid_email("a@b.co")
    assert not valid_email("nope")
    assert not valid_email("")
    assert not valid_email(None)


def test_double_booking_same_slot_is_rejected(monkeypatch):
    monkeypatch.setattr(config, "GCAL_ENABLED", False)
    slot, _ = _book_first_slot("L001")
    again = execute_tool(
        "book_meeting",
        {"slot_iso": slot["iso"], "slot_label": slot["label"], "attendee_email": EMAIL},
        "L002",
    )
    assert again["booked"] is False
    assert again["reason"] == "slot_taken"


def test_booked_slot_excluded_from_availability(monkeypatch):
    monkeypatch.setattr(config, "GCAL_ENABLED", False)
    slot, _ = _book_first_slot("L001")
    later = execute_tool("check_availability", {"count": 3}, "L002")["slots"]
    assert all(s["iso"] != slot["iso"] for s in later)


def test_book_meeting_gcal_success(monkeypatch):
    monkeypatch.setattr(config, "GCAL_ENABLED", True)
    monkeypatch.setattr(
        "alex.google_calendar.create_event",
        lambda iso, email: {
            "ok": True,
            "event_id": "evt_123",
            "event_link": "https://cal/evt_123",
            "meet_link": "https://meet.google.com/abc",
        },
    )
    _, result = _book_first_slot("L001")
    assert result["booked"] is True
    assert result["status"] == "calendar_invite_sent"
    assert result["meet_link"] == "https://meet.google.com/abc"
    lead = crm.get_lead("L001")
    assert lead["status"] == "calendar_invite_sent"
    assert lead["meeting"]["event_id"] == "evt_123"


def test_book_meeting_gcal_failure_does_not_claim_sent(monkeypatch):
    monkeypatch.setattr(config, "GCAL_ENABLED", True)
    monkeypatch.setattr(
        "alex.google_calendar.create_event",
        lambda iso, email: {"ok": False, "error": "quota exceeded"},
    )
    slot, result = _book_first_slot("L001")
    assert result["booked"] is False
    assert result["manual_follow_up"] is True
    lead = crm.get_lead("L001")
    assert lead["status"] == "calendar_invite_failed"
    # Slot stays reserved for manual follow-up.
    later = execute_tool("check_availability", {"count": 3}, "L002")["slots"]
    assert all(s["iso"] != slot["iso"] for s in later)


def test_opt_out_flags_lead():
    result = execute_tool("opt_out", {"reason": "do not call"}, "L003")
    assert result["acknowledged"] is True
    assert crm.get_lead("L003")["status"] == "opt_out"


def test_log_outcome_records_disposition():
    execute_tool("log_outcome", {"outcome": "callback", "notes": "ring back next week"}, "L005")
    lead = crm.get_lead("L005")
    assert lead["disposition"] == "callback"
    assert lead["status"] == "callback"


def test_log_outcome_does_not_downgrade_booking(monkeypatch):
    monkeypatch.setattr(config, "GCAL_ENABLED", False)
    _book_first_slot("L001")
    execute_tool("log_outcome", {"outcome": "not_interested", "notes": "n/a"}, "L001")
    assert crm.get_lead("L001")["status"] == "reserved_pending_calendar_invite"


def test_book_meeting_missing_arg_returns_error_not_crash():
    result = execute_tool("book_meeting", {}, "L001")
    assert result["booked"] is False
    assert "error" in result


def test_log_outcome_rejects_invalid_outcome():
    result = execute_tool("log_outcome", {"outcome": "definitely_buying"}, "L001")
    assert "error" in result
    assert crm.get_lead("L001")["disposition"] is None  # nothing written


def test_unknown_lead_returns_error():
    assert "error" in execute_tool("check_availability", {}, "NOPE")


def test_check_availability_count_is_clamped():
    assert len(execute_tool("check_availability", {"count": 99}, "L001")["slots"]) == 5
    assert len(execute_tool("check_availability", {"count": "bad"}, "L002")["slots"]) == 2


def test_slot_label_includes_timezone():
    slot = execute_tool("check_availability", {"count": 1}, "L001")["slots"][0]
    assert slot["label"].endswith(" " + config.SLOT_TZ_LABEL)


def test_schema_adapters_cover_all_tools():
    names = {s["name"] for s in TOOL_SPECS}
    assert {t["name"] for t in anthropic_tools()} == names
    vt = vapi_tools("https://example.test/webhook")
    assert {t["function"]["name"] for t in vt} == names
    assert all(t["server"]["url"].endswith("/webhook") for t in vt)
