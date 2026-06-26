"""Tests for dashboard-backing CRM operations: add / delete / reset_lead."""
from __future__ import annotations

import pytest

from alex import config, crm
from alex.tools import execute_tool


@pytest.fixture(autouse=True)
def fresh_crm():
    crm.reset()
    yield
    crm.reset()


def test_leads_have_phone_field():
    assert crm.get_lead("L001")["phone"] == "+972503095725"
    assert crm.get_lead("L003")["phone"] is None


def test_add_lead_gets_new_id_and_defaults():
    before = len(crm.list_leads())
    lead = crm.add_lead(name="Test Person", email="t@x.co", phone="+10000000000", company="Acme")
    assert lead["lead_id"] not in [l["lead_id"] for l in crm.list_leads()[:before]]
    assert lead["status"] == "new"
    assert lead["email"] == "t@x.co" and lead["phone"] == "+10000000000"
    assert len(crm.list_leads()) == before + 1
    assert crm.get_lead(lead["lead_id"])["company"] == "Acme"


def test_delete_lead():
    lead = crm.add_lead(name="Temp")
    assert crm.delete_lead(lead["lead_id"]) is True
    assert crm.get_lead(lead["lead_id"]) is None
    assert crm.delete_lead("does-not-exist") is False


def test_reset_lead_clears_call_state_and_frees_slot(monkeypatch):
    monkeypatch.setattr(config, "GCAL_ENABLED", False)
    slot = execute_tool("check_availability", {"count": 1}, "L001")["slots"][0]
    execute_tool(
        "book_meeting",
        {"slot_iso": slot["iso"], "slot_label": slot["label"], "attendee_email": "h@x.co"},
        "L001",
    )
    assert crm.get_lead("L001")["status"] == "reserved_pending_calendar_invite"

    reset = crm.reset_lead("L001")
    assert reset["status"] == "new"
    assert reset["meeting"] is None and reset["transcript"] is None
    assert crm.get_lead("L001")["name"] == "Harel Gil"  # identity preserved

    # Freed slot is offered again.
    later = execute_tool("check_availability", {"count": 3}, "L002")["slots"]
    assert any(s["iso"] == slot["iso"] for s in later)


def test_reset_lead_unknown_returns_none():
    assert crm.reset_lead("NOPE") is None
