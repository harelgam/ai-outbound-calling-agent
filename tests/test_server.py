"""Tests for webhook secret verification and tool-truth precedence at end-of-call.

These run offline: summarize() falls back deterministically with no API key.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from alex import config, crm, server
from alex.tools import execute_tool


@pytest.fixture(autouse=True)
def fresh_crm():
    crm.reset()
    yield
    crm.reset()


def _fake_request(headers=None, query=None):
    return SimpleNamespace(headers=headers or {}, query_params=query or {})


# --------------------------- webhook secret ------------------------------- #
def test_no_secret_configured_allows_any_request(monkeypatch):
    monkeypatch.setattr(config, "WEBHOOK_SECRET", "")
    server._verify_secret(_fake_request())  # should not raise


def test_correct_secret_header_passes(monkeypatch):
    monkeypatch.setattr(config, "WEBHOOK_SECRET", "s3cret")
    server._verify_secret(_fake_request(headers={"x-vapi-secret": "s3cret"}))


def test_query_param_secret_is_rejected(monkeypatch):
    # Header-only by design: a secret in the URL would leak into logs.
    from fastapi import HTTPException

    monkeypatch.setattr(config, "WEBHOOK_SECRET", "s3cret")
    with pytest.raises(HTTPException) as exc:
        server._verify_secret(_fake_request(query={"secret": "s3cret"}))
    assert exc.value.status_code == 401


def test_wrong_secret_is_rejected(monkeypatch):
    from fastapi import HTTPException

    monkeypatch.setattr(config, "WEBHOOK_SECRET", "s3cret")
    with pytest.raises(HTTPException) as exc:
        server._verify_secret(_fake_request(headers={"x-vapi-secret": "nope"}))
    assert exc.value.status_code == 401


# ------------------------ tool-truth precedence --------------------------- #
def test_end_of_call_never_overwrites_opt_out():
    execute_tool("opt_out", {"reason": "do not call"}, "L001")
    server._handle_end_of_call({"transcript": "Prospect: book it, confirmed"}, "L001")
    assert crm.get_lead("L001")["status"] == "opt_out"


def test_end_of_call_preserves_booking(monkeypatch):
    monkeypatch.setattr(config, "GCAL_ENABLED", False)
    slot = execute_tool("check_availability", {"count": 1}, "L002")["slots"][0]
    execute_tool(
        "book_meeting",
        {"slot_iso": slot["iso"], "slot_label": slot["label"], "attendee_email": "b@x.co"},
        "L002",
    )
    server._handle_end_of_call({"transcript": "wishy washy, not interested"}, "L002")
    lead = crm.get_lead("L002")
    assert lead["status"] == "reserved_pending_calendar_invite"
    assert lead["meeting"]["iso"] == slot["iso"]  # slot not clobbered


def test_summary_only_booked_is_downgraded():
    # No book_meeting tool fired; a summary that claims "booked" must not stick.
    server._handle_end_of_call({"transcript": "let's book it, confirmed Tuesday"}, "L003")
    assert crm.get_lead("L003")["status"] == "callback"
