"""One-time Google Calendar OAuth helper.

    python -m alex.google_calendar_auth

Opens a browser, completes the OAuth consent flow against
GCAL_CREDENTIALS_PATH, and writes the refreshable token to GCAL_TOKEN_PATH.
Run once before using GCAL_ENABLED=true.
"""
from __future__ import annotations

from pathlib import Path

from . import config
from .google_calendar import SCOPES


def main() -> int:
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds_path = Path(config.GCAL_CREDENTIALS_PATH)
    if not creds_path.exists():
        print(
            f"Missing OAuth client file at {creds_path}.\n"
            "Create an OAuth client (Desktop app) in Google Cloud Console, enable the "
            "Google Calendar API, download the JSON, and save it there."
        )
        return 1

    flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
    creds = flow.run_local_server(port=0)

    token_path = Path(config.GCAL_TOKEN_PATH)
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json(), encoding="utf-8")
    print(f"Saved token to {token_path}. Set GCAL_ENABLED=true to send real invites.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
