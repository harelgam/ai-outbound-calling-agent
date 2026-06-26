"""Tests for the wrong-person -> referral-capture flow.

When Alex reaches someone who is not responsible for pipeline/outreach and they
name the right contact, `capture_referral` turns that dead end into a new
follow-up lead instead of a lost call. These run offline (no API key, no network).
"""
from __future__ import annotations

import pytest

from alex import crm
from alex.tools import TERMINAL_TOOLS, TOOL_SPECS, execute_tool


@pytest.fixture(autouse=True)
def fresh_crm():
    crm.reset()
    yield
    crm.reset()


def test_capture_referral_creates_linked_lead():
    before = len(crm.list_leads())
    source = crm.get_lead("L001")

    res = execute_tool(
        "capture_referral",
        {
            "referred_name": "Sarah Lin",
            "referred_title": "VP Sales",
            "referred_email": "sarah@example.com",
            "referred_phone": "+15551230000",
        },
        "L001",
    )
    assert res["captured"] is True
    new_id = res["new_lead_id"]
    assert len(crm.list_leads()) == before + 1

    new_lead = crm.get_lead(new_id)
    assert new_lead["name"] == "Sarah Lin"
    assert new_lead["title"] == "VP Sales"
    assert new_lead["email"] == "sarah@example.com"
    assert new_lead["phone"] == "+15551230000"
    assert new_lead["company"] == source["company"]      # inherits the company
    assert new_lead["status"] == "new"                   # a fresh, callable lead
    assert "Referred by" in new_lead["signal"]
    assert "L001" in (new_lead["next_action"] or "")

    # The source lead records the handoff.
    src = crm.get_lead("L001")
    assert src["referred_to"]["lead_id"] == new_id
    assert src["referred_to"]["name"] == "Sarah Lin"


def test_capture_referral_requires_name():
    res = execute_tool("capture_referral", {"referred_name": "  "}, "L001")
    assert res["captured"] is False
    assert "error" in res


def test_capture_referral_drops_invalid_email_but_still_captures():
    res = execute_tool(
        "capture_referral",
        {"referred_name": "Pat Doe", "referred_email": "not-an-email"},
        "L002",
    )
    assert res["captured"] is True
    assert "warning" in res
    assert crm.get_lead(res["new_lead_id"])["email"] is None  # bad address dropped


def test_capture_referral_is_not_terminal():
    assert "capture_referral" in {s["name"] for s in TOOL_SPECS}
    assert "capture_referral" not in TERMINAL_TOOLS  # the call continues afterward


def test_capture_referral_unknown_lead_errors():
    res = execute_tool("capture_referral", {"referred_name": "X"}, "NOPE")
    assert "error" in res


def test_wrong_person_flow_end_to_end():
    """Reached the wrong person -> capture the referral -> log wrong_person."""
    ref = execute_tool("capture_referral", {"referred_name": "Dana Ops"}, "L004")
    assert ref["captured"] is True

    out = execute_tool(
        "log_outcome", {"outcome": "wrong_person", "notes": "referred to Dana"}, "L004"
    )
    assert out["acknowledged"] is True

    src = crm.get_lead("L004")
    assert src["disposition"] == "wrong_person"
    # The referred contact survives as a new lead to follow up on.
    assert crm.get_lead(ref["new_lead_id"])["status"] == "new"
