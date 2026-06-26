"""Central configuration: model IDs, env vars, and paths.

Two Claude models are used deliberately:
- CALLER_MODEL  (Sonnet 4.6): the realtime voice loop — latency matters most.
- HELPER_MODEL  (Opus 4.8):  offline brief()/summarize() — quality matters most.
"""
from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # python-dotenv is optional at runtime
    pass

# --- Claude models (override via env; exact IDs, no date suffixes) ---
CALLER_MODEL = os.environ.get("CALLER_MODEL", "claude-sonnet-4-6")    # realtime caller (also set on Vapi)
HELPER_MODEL = os.environ.get("HELPER_MODEL", "claude-opus-4-8")      # offline brief() / summarize()
PROSPECT_MODEL = os.environ.get("PROSPECT_MODEL", "claude-sonnet-4-6")  # eval: role-plays the prospect
JUDGE_MODEL = os.environ.get("JUDGE_MODEL", "claude-opus-4-8")          # eval: grades the transcript

# --- Credentials / wiring ---
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
VAPI_API_KEY = os.environ.get("VAPI_API_KEY", "")
VAPI_PHONE_NUMBER_ID = os.environ.get("VAPI_PHONE_NUMBER_ID", "")
VAPI_ASSISTANT_ID = os.environ.get("VAPI_ASSISTANT_ID", "")
DEMO_CALL_NUMBER = os.environ.get("DEMO_CALL_NUMBER", "")
PUBLIC_WEBHOOK_URL = os.environ.get("PUBLIC_WEBHOOK_URL", "").rstrip("/")
# Shared secret for webhook authenticity. When set, Vapi sends it as the
# `x-vapi-secret` header and the server rejects requests that don't match.
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")

VAPI_BASE_URL = "https://api.vapi.ai"


def _env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


# --- Meeting / calendar ---
SALES_TEAM_EMAIL = os.environ.get("SALES_TEAM_EMAIL", "team@harels.example")
MEETING_MINUTES = 30  # 30-minute remote discovery call with Harel's sales team

# Google Calendar (optional, gated). When disabled, book_meeting reserves a slot
# and marks it pending a manual invite; the rest of the demo runs unchanged.
GCAL_ENABLED = _env_bool("GCAL_ENABLED", False)
GCAL_CALENDAR_ID = os.environ.get("GCAL_CALENDAR_ID", "primary")
GCAL_CREDENTIALS_PATH = os.environ.get("GCAL_CREDENTIALS_PATH", "secrets/google_credentials.json")
GCAL_TOKEN_PATH = os.environ.get("GCAL_TOKEN_PATH", "secrets/google_token.json")
GCAL_CREATE_MEET = _env_bool("GCAL_CREATE_MEET", True)

# --- Paths ---
PKG_DIR = Path(__file__).resolve().parent
ROOT_DIR = PKG_DIR.parent
DATA_DIR = ROOT_DIR / "data"
LEADS_CSV = PKG_DIR / "leads.csv"
CRM_STORE = DATA_DIR / "crm.json"

# Demo voice/transcriber for the Vapi assistant (override freely in the dashboard).
VAPI_VOICE = {"provider": "vapi", "voiceId": "Elliot"}
VAPI_TRANSCRIBER = {"provider": "deepgram", "model": "nova-2", "language": "en"}

# Display timezone for proposed slots. The mock uses one fixed zone; production
# must resolve the prospect's actual timezone from the CRM before offering times.
SLOT_TZ_LABEL = os.environ.get("SLOT_TZ_LABEL", "ET")
SLOT_IANA_TZ = os.environ.get("SLOT_IANA_TZ", "America/New_York")  # used for real calendar events
