# Alex — AI Outbound Calling Agent (Design)

> Design an AI-driven speaking calling agent that
> pitches Harel's value proposition and books meetings for the sales team.

## 1. Problem & framing

Harel's sells a "revenue workforce" of AI agents — including **Alex**, an AI calling
agent. This project is a focused, runnable version of Alex: it places a real
outbound call, discloses it's an AI, pitches Harel's, handles objections, and books
a 30-minute remote discovery call via calendar tool-calls — then writes the outcome back
to the CRM.

Scope is deliberately **one agent**. A pre-call brief and a post-call summary
exist only as lightweight helper functions around Alex (mirroring how Harel's
Katie/Luna would feed and follow a call), not as separate core agents.

## 2. Architecture

```
 leads.csv ──► Mock CRM (data/crm.json)
                   │
                   ▼  brief(lead)            [helper · Claude Opus 4.8, one call]
              CallBrief (angle, opener, talking points, likely objections)
                   │
                   ▼
   ┌──────────────────────────────────────────────────────────────────┐
   │  ALEX  (the calling agent)                                         │
   │                                                                    │
   │  LIVE PATH                         EVAL PATH                       │
   │  Vapi assistant                    alex/agent.py                   │
   │  STT → Claude Sonnet 4.6 → TTS     Claude tool-use loop in text    │
   │        (over the phone)            (vs simulated prospect)         │
   │                  └──────── same system prompt + same tools ───────┘│
   │                                   │                                │
   │                                   ▼  tool calls                    │
   │  check_availability · book_meeting · capture_referral · opt_out · log_outcome │
   │                                   │                                │
   │   live: Vapi → FastAPI webhook ───┘   eval: in-process            │
   │                          └──────► alex/tools.execute_tool ────────►│ CRM + calendar
   └──────────────────────────────────────────────────────────────────┘
                   │
                   ▼  summarize(transcript)  [helper · Claude Opus 4.8, one call]
              CallSummary → CRM disposition (booked / callback / opt_out / …)
```

**The key design decision** is that the conversation logic lives in *one* system
prompt (`alex/prompts.py`) and *one* tool set (`alex/tools.py`), and **both** the
live phone path and the offline eval path drive that same prompt + tools. The
phone call and the test harness can't drift apart, and the eval is a faithful
proxy for production behavior.

## 3. Stack choices & rationale

| Layer | Choice | Why |
|---|---|---|
| Voice platform | **Vapi** (managed) | Outbound calls, STT/LLM/TTS orchestration, function-calling, and an end-of-call webhook out of the box — a real phone call in hours, not days. Retell is a drop-in alternative. |
| Realtime LLM | **Claude Sonnet 4.6** | The caller is latency-sensitive; Sonnet 4.6 balances speed and quality. (Swap to Haiku 4.5 if you want lower latency still.) |
| Offline LLM | **Claude Opus 4.8** | `brief()`, `summarize()`, and the eval judge are quality-sensitive and off the hot path. |
| Tools server | **FastAPI** + ngrok | Receives Vapi tool-calls and the end-of-call report. |
| CRM | **Mock (JSON)** | Stands in for Salesforce/HubSpot; zero-dependency and inspectable for the demo. |
| Calendar | **Google Calendar** (gated) or mock | `book_meeting` sends a real 30-min invite + Meet link when `GCAL_ENABLED=true`; otherwise reserves the slot and marks it pending a manual invite. |

**Architecture pattern:** cascading **STT → LLM → TTS** (what Vapi runs), chosen
over speech-to-speech because it gives a clean text transcript for tool-calling,
logging, compliance review, and evaluation. The latency cost (~1–2s/turn) is
acceptable for a B2B intro call; a latency-critical deployment could move to S2S.

## 4. Conversation design

System prompt (`alex/prompts.py`) encodes the playbook:

1. **Open** — greet by first name, **disclose Alex is Harel's AI assistant**, give
   the one tailored reason for calling, ask permission to continue.
2. **Pitch** — 1–2 sentence value prop personalized from the brief's *angle*
   (not a static script).
3. **Qualify** — confirm they own/influence top-of-funnel or pipeline.
4. **Objections** — honest, brief handling for *not interested / no time / just
   email me / who are you*.
5. **CTA** — `check_availability` → offer two concrete slots → **confirm the email
   for the invite** → `book_meeting` → confirm per the tool's result.
6. **Close** — exactly one `log_outcome` (or `opt_out`) ends every call.

Edge cases covered in the prompt: voicemail (leave a short disclosed message →
`log_outcome: voicemail`), wrong person, and gatekeeper. When the wrong person
names the right contact, Alex calls `capture_referral` → a new follow-up lead is
created (inheriting the company, linked back to the source) before logging
`wrong_person`, so a dead-end call turns into a fresh opportunity.

### Booking the meeting (the deliverable)

The meeting is a **30-minute remote discovery call with Harel's sales team**.
`book_meeting` requires a validated `attendee_email` — Alex confirms the email on
file or asks for one before booking. Booking is **honest about what happened**:

| Condition | CRM status | Alex says |
|---|---|---|
| `GCAL_ENABLED=true`, invite sent | `calendar_invite_sent` | "I booked the 30-minute discovery call and sent the calendar invite to <email>." (+ Meet link) |
| `GCAL_ENABLED=false` | `reserved_pending_calendar_invite` | "I reserved the call; the Harel's team will follow up with an invite at <email>." |
| Calendar API failed | `calendar_invite_failed` | does **not** claim an invite was sent; team will follow up |

A real invite goes out via Google Calendar (`alex/google_calendar.py`,
`sendUpdates="all"`, optional Meet link), with the prospect and `SALES_TEAM_EMAIL`
as attendees. All three statuses are "booked-ish" and protected from being
overwritten by the post-call summary (tool-truth precedence, §5).

## 5. Guardrails & compliance

These are first-class because a calling-agent company lives or dies on them:

- **AI self-disclosure** in the first sentence of every call (state-law trend +
  trust). Enforced in the prompt and checked by the eval.
- **Recording/transcription notice** early in the call — the call is transcribed
  (STT) and stored, and two-party-consent states require disclosing recording,
  not just that it's an AI. If the prospect objects to recording, Alex opts out.
- **Opt-out / DNC** — any "stop / remove me / don't call" triggers the `opt_out`
  tool immediately and ends the call; the lead is flagged `opt_out` and excluded
  from future calling. No objection-handling on consent withdrawal.
- **Grounded selling** — the pitch may use *only* the fixed `HARELS_FACTS` block.
  Alex is instructed to defer unknowns (pricing, security specifics) to the human
  specialist rather than invent claims. The eval judge scores "stayed grounded".
- **Consent assumption** (documented, not enforced in the mock) — leads are
  treated as B2B and opted-in; a production system would check a DNC list,
  calling hours/timezone, and per-jurisdiction consent (TCPA) before dialing.
- **Human handoff** — out-of-scope or high-intent calls would transfer to a rep
  (Vapi supports call transfer; wired as a future tool).
- **Tool-truth precedence** — tool calls made *during* the call outrank the
  post-call LLM summary. The end-of-call handler never lets `summarize()` undo an
  `opt_out` (a DNC compliance fact) or clobber a confirmed `book_meeting`, and a
  "booked" status can only originate from the booking tool, never the summary.
- **Webhook authenticity** — when `WEBHOOK_SECRET` is set, it's passed to Vapi as
  `server.secret`; Vapi returns it as the `x-vapi-secret` header and the server
  rejects any request that doesn't match (a header, not a URL query param, so the
  secret isn't written to proxy/access logs).

## 6. Evaluation (`eval/`)

A text simulation — **no telephony, fast, CI-able** — that runs Alex's *real*
prompt + tools against Claude-role-played prospect personas:

| Persona | Behavior | Expected |
|---|---|---|
| `interested` | warm VP Sales with SDR-hiring pain | **booked** |
| `busy` | time-pressed, pushes back, then agrees to a short slot | **booked** |
| `hostile_optout` | annoyed founder, demands removal | **opt_out honored** |

The scorecard combines **rule-based metrics** (disclosed? booked via tool?
opt-out honored?) with an **LLM judge** (objection handling, grounded claims,
1–5 professionalism). This maps directly to the JD's "evaluate agent performance
using live data" — the same harness would run against recorded real calls.

## 7. From prototype to production

- **CRM context layer** — replace the JSON mock with Harel's semantic layer over
  Salesforce/HubSpot + 50+ sources; `brief()` becomes a richer research step
  (this is where Katie hands off to Alex).
- **Calendar** — real Google Calendar invites are wired (gated by `GCAL_ENABLED`);
  production would add real-time availability sync and per-prospect timezone, and
  create the event on a shared sales calendar so any rep is the organizer.
- **Post-call** — `summarize()` is the Luna/RevOps writeback; add CRM task
  creation, sequence enrollment, and rep notification.
- **Scale & cost** — Vapi is "buy" for fast launch; above ~10–50K min/month a
  framework (LiveKit/Pipecat) self-hosted can cut cost substantially. The
  prompt + tools port unchanged because they're provider-neutral here.
- **Observability** — per-call latency, interruption rate, booked-rate, opt-out
  rate, transcript QA (the eval judge, run on real transcripts).

## 8. Metrics that matter

Connect rate · talk-through rate (got past the opener) · **meeting-booked rate**
· qualified-booked rate · opt-out rate · disclosure compliance (should be 100%) ·
mean turn latency · cost per booked meeting.

## 9. Limitations / assumptions

- Mock CRM; English-only; single timezone for slots. Calendar invites assume the
  authenticated Google account is the sales-team organizer (see code note in
  `alex/google_calendar.py` if `SALES_TEAM_EMAIL` is a different account).
- Vapi API field names can shift between versions — `alex/vapi_client.py` notes
  where to check; the structure (model/voice/transcriber/tools/server) is stable.
- `ANTHROPIC_API_KEY` powers the local `brief`/`summarize`/`eval` only. **Vapi runs
  the call's LLM server-side** and must be configured separately (billing + model
  provider key in the Vapi dashboard); the local key does not configure Vapi.
- The eval and live call require an `ANTHROPIC_API_KEY`; the unit tests do not.
```
