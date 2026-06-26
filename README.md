# Alex — AI Outbound Calling Agent

Alex places a **real outbound phone call**, discloses it's an AI, pitches Harel's
value proposition, handles objections, and **books a meeting** via calendar
tool-calls — then writes the outcome back to a mock CRM. If it reaches the wrong
person who names the right contact, it **captures that referral** as a new
follow-up lead instead of losing the call.

One agent. A pre-call `brief()` and post-call `summarize()` are lightweight
helpers around it. The full design is in **[DESIGN.md](DESIGN.md)**.

```
alex/
  prompts.py      Alex's system prompt + grounded Harel's facts + conversation design
  tools.py        check_availability · book_meeting · capture_referral · opt_out · log_outcome (shared)
  crm.py          mock CRM + calendar (JSON store, seeded from leads.csv)
  brief.py        brief(lead)        -> personalized call brief   (Claude Opus 4.8)
  summarize.py    summarize(script)  -> CRM disposition           (Claude Opus 4.8)
  agent.py        local Alex tool-use loop (text) — shared brain for the eval
  vapi_client.py  build the Vapi assistant + place the outbound call
  server.py       FastAPI webhook: tool-calls + end-of-call report
  google_calendar.py        create a real 30-min invite (+ Meet link), gated
  google_calendar_auth.py   one-time Google OAuth helper
  run.py          campaign runner  ← the live demo entry point
  show.py         print CRM state (incl. invite + Meet links)
eval/             3 personas + scorecard (no telephony)
tests/            unit tests for the tool layer (offline)
```

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env                       # then fill in keys
cp alex/leads.example.csv alex/leads.csv   # sample leads — edit with your own
```

> `alex/leads.csv` is gitignored (it can hold real contact details), so the repo
> ships `alex/leads.example.csv` instead. Copy it as above before running.

Required for the eval and the live call: `ANTHROPIC_API_KEY`.
Required for the live call only: a Vapi account (`VAPI_API_KEY`,
`VAPI_PHONE_NUMBER_ID`) and a public `PUBLIC_WEBHOOK_URL`.

## 1. Unit tests (offline, no keys)

```bash
python -m pytest tests/ -q
```

## 2. Evaluation (needs ANTHROPIC_API_KEY, no phone)

Runs Alex's real prompt + tools against simulated prospects and prints a scorecard.

```bash
python -m eval.run_eval            # summary table
python -m eval.run_eval --verbose  # also print transcripts
```

Expected: `interested` and `busy` → **booked**; `hostile_optout` → **opt-out honored**.

## Operator dashboard (GUI)

A local web UI to see customers, place calls, read transcripts/summaries, and
add / delete / reset customers. It runs on a **separate port that is NOT tunnelled
by ngrok**, so customer data and the Call button stay private (only the webhook is
public).

```bash
uvicorn alex.dashboard:app --port 8001     # then open http://localhost:8001
```

To place calls **from** the dashboard, the public webhook server + ngrok must also
be running (Vapi calls back to them):

```bash
uvicorn alex.server:app --port 8000        # terminal 1 (webhook)
ngrok http 8000                            # terminal 2 (tunnel)
uvicorn alex.dashboard:app --port 8001     # terminal 3 (GUI)
```

The dashboard auto-refreshes, so a call's status/transcript/summary appear as the
call completes. "Call" is disabled for customers with no phone number. "Reset"
clears one customer's call result (and frees their slot) so you can re-demo the
same lead.

## 2b. Booking smoke test (pre-flight, no Vapi)

Verify the booking half works on its own before placing a real call. Mock mode
needs no keys; with `GCAL_ENABLED=true` it sends a real invite to `--email`.

```bash
python -m alex.test_booking --lead L001 --email you@example.com
```

## 3. Live demo (the centerpiece) — a real phone call

> **Configure Vapi first.** Vapi runs the assistant's LLM server-side — your local
> `.env` `ANTHROPIC_API_KEY` powers only `brief`, `summarize`, and `eval`; it does
> **not** configure Vapi's hosted assistant. Before running `python -m alex.run`,
> in the Vapi dashboard: (1) add billing/credits; (2) confirm the assistant's
> model **provider is configured and billable** — if you keep the Anthropic
> provider (`CALLER_MODEL`), add your Anthropic provider key in Vapi; otherwise
> switch the assistant to a Vapi-supported default provider/model.

```bash
# Terminal A — tool + end-of-call webhook server
uvicorn alex.server:app --port 8000
ngrok http 8000                    # put the https URL in PUBLIC_WEBHOOK_URL

# Terminal B — place the call to your own phone
python -m alex.run --lead L001 --to +14155550123
```

Your phone rings, you talk to Alex, you book (or decline) a meeting. After the
call the webhook summarizes the transcript and updates the CRM:

```bash
python -m alex.show
```

Record this call as the demo artifact.

## Real Google Calendar invites (optional)

By default (`GCAL_ENABLED=false`) `book_meeting` reserves the slot and marks it
`reserved_pending_calendar_invite`. To send a **real 30-minute invite + Google
Meet link** to the prospect:

1. In Google Cloud Console: create a project, **enable the Google Calendar API**,
   and create an **OAuth client ID (Desktop app)**. Download the JSON to
   `secrets/google_credentials.json`.
2. Authorize once (opens a browser):
   ```bash
   python -m alex.google_calendar_auth      # writes secrets/google_token.json
   ```
3. In `.env` set `GCAL_ENABLED=true` and `SALES_TEAM_EMAIL=...` (the organizer /
   who the prospect meets; defaults to `team@harels.example`).

On a successful call Alex says it sent the invite; the invite lands in the
prospect's inbox and `python -m alex.show` prints the event + Meet links. If the
Calendar API fails, Alex does **not** claim an invite was sent (status
`calendar_invite_failed`, flagged for manual follow-up).

> **Never commit `.env` or `secrets/`** — both are gitignored. They hold your API
> keys and Google OAuth tokens.

## Notes

- Models: Sonnet 4.6 drives the realtime call; Opus 4.8 runs `brief()`,
  `summarize()`, and the eval judge.
- `brief()` and `summarize()` fall back to deterministic output if no API key is
  set, so the structure is inspectable without one.
- Vapi API field names occasionally change between versions; `alex/vapi_client.py`
  flags where to check against current Vapi docs.
```
