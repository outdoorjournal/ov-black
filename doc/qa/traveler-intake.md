# QA — Immersive traveler intake (`/itinerary/{id}/new`)

The full-screen "Where shall we take you?" form is retired for travelers. A
brand-new, traveler-owned trip instead lands on `/itinerary/{id}/new`: an
immersive, landing-page-dark screen with ambient imagery and a floating chat
with Artemis. The agent's job there is **information gathering only** — name
the adventure, who's coming, a rough or exact block of time, what the traveler
wants to experience — plus profile/dossier recording. It does NOT build the
trip. When the traveler skips or tells Artemis to move on, the chat docks to
its normal left column and the traveler is on the trip dashboard with the same
session continuing.

Verification legend: **[unit]** vitest/pytest · **[e2e-api]** `ovb` against the
local stack (real agent on :8080, `EMIT_TOOL_TRACE=1`) · **[e2e-ui]**
Playwright MCP against `next dev`.

**Status (2026-07-10, local stack + live agent): all scenarios PASS.**
QA-1/2/3/10/12/13/14 verified in-browser; QA-5/6/9/11 verified against the
live agent (tool trace: `get_traveler_context → record_profile_fact ×2 →
record_party_member → update_trip_details → update_trip_timing → set_mood`,
then `complete_intake` on "let's move on"; trunk untouched, fork carried
title/brief/timing). QA-4 covered by the gate condition (`isOwnBuild`) +
unit suites; QA-15 = 542 web / 117 agent / 1061 api tests, ruff + mypy +
tsc + eslint all green. Known follow-up: `record_party_member` writes the
durable household member (the intake details card shows them), but nothing
yet attaches them to the trip's own travelers edge — the dashboard party
chip still reads "Just you" after intake names a companion.

---

## Routing & gating

### QA-1 New traveler-owned trip redirects to `/new`
- **Given** a traveler whose own trunk itinerary has an empty `brief`, no
  content nodes, and no open fork
- **When** they visit `/itinerary/{trunkId}` (or `/dashboard`, `/timeline`)
- **Then** they are redirected to `/itinerary/{id}/new` and see the immersive
  intake: dark full-bleed imagery, centered floating Artemis chat, a visible
  "Skip for now" affordance, and **no** planner chrome (no rail, no concierge
  column, no journal).
- [e2e-ui]

### QA-2 Established trip never sees `/new`
- **Given** an itinerary whose effective working copy has a non-empty brief
  (or any content node)
- **When** the traveler visits `/itinerary/{id}` or `/itinerary/{id}/new`
  directly
- **Then** they land on `/itinerary/{id}/dashboard` — the intake never gates
  an established trip.
- [e2e-ui]

### QA-3 Advisors never see `/new`
- **Given** an advisor visiting a brand-new empty trunk
- **Then** current behavior is preserved (the in-shell "What are we planning?"
  form), and a direct visit to `/new` redirects to `/dashboard`.
- [e2e-ui]

### QA-4 Invited traveler on an advisor-crafted trunk is untouched
- **Given** a traveler on a trunk they did **not** create (advisor-crafted,
  nothing published)
- **Then** no `/new` redirect — they see the existing "being crafted" teaser.
- [unit] (gate condition) / [e2e-ui] spot-check

## Fork correctness

### QA-5 Everything lands on the traveler's fork, right out of the gate
- **Given** a traveler entering `/new` on their own empty trunk
- **Then** an open fork exists (created if missing, reused if present), the
  chat session is pinned to the **fork**, and every write the agent makes
  during intake (title, brief, timing, party, facts) lands on the fork — the
  trunk row is unchanged. No `409 fork_required` is possible during or after
  intake: the traveler can chat and edit immediately.
- **And** subsequent visits to the trunk URL resolve to the fork (existing
  solo-traveler redirect).
- [e2e-api] — `ovb`: create trip as traveler, run intake turns, assert fork
  exists, trunk untouched, fork carries the metadata.

## The intake conversation

### QA-6 Artemis opens the conversation and gathers, not builds
- **Given** the traveler lands on `/new`
- **Then** Artemis speaks first (a seeded opener in the spirit of "Where shall
  we take you?").
- **When** the traveler describes what they want (e.g. "a week of climbing in
  the Dolomites with my brother, sometime in September")
- **Then** over the conversation the agent:
  - names the adventure (trip **title**) and captures the **brief**,
  - captures **timing** (`exact` dates, a window, or flexible + note),
  - establishes the **party** — solo, existing party members by name, or new
    companions recorded via `record_party_member`,
  - records `profile_facts` / `dossier_inferences` where warranted,
- **And** the agent does **not** build the trip: no `card_proposed`, no
  `draft_assembled`, no node writes — the building tools are not in the
  intake toolset.
- [e2e-api] — tool-trace assertion: `update_trip_details` /
  `update_trip_timing` / party+fact tools allowed; propose/assemble tools
  absent from the trace **and** from the mode's toolset.

### QA-7 Details fill in live as they talk
- **Given** an intake conversation in progress
- **When** the agent sets the title/brief/timing or records a party member
- **Then** the immersive screen's details panel (name · who · when) updates in
  the same turn, driven by SSE frames (`itinerary_updated`, `party_updated`)
  — no page refresh.
- [unit] frame-reducer tests / [e2e-ui]

### QA-8 Ambient imagery shifts with the conversation
- **Given** the immersive screen with its default dark rotating imagery
- **When** the conversation turns to a concrete place/feel and the agent calls
  `set_mood` (e.g. kyoto-zen, highland)
- **Then** the backdrop cross-fades to that mood's imagery while staying dark
  and legible (landing-page veil treatment). `prefers-reduced-motion` gets a
  cut, not a fade.
- (Lottie line-art vignettes are a future flourish — explicitly out of scope.)
- [unit] mood-frame → backdrop-state test / [e2e-ui] spot-check

## Leaving intake

### QA-9 "Move on" docks the chat and lands on the dashboard
- **Given** an intake conversation with at least the title or brief captured
- **When** the traveler tells Artemis to move on (or Artemis judges intake
  complete)
- **Then** the agent calls `complete_intake` → an `intake_complete` SSE frame
  → the immersive screen transitions out (imagery fades to paper, chat docks
  left) and the traveler is on `/itinerary/{forkId}/dashboard` with the
  concierge column open on the same session.
- **And** Artemis's parting message invites continuing the conversation about
  the itinerary.
- [e2e-api] frame assertion + [e2e-ui] full flow

### QA-9b A parting line without the hand-off is a bug
- **Given** any wind-down from the traveler — "that's enough", "I'll come
  back to this", a satisfied close — or Artemis itself writing a parting
  line ("the journal is open", "I'm right here")
- **Then** `complete_intake` fires in that same turn. The rubric's mirror
  rule makes the parting line itself the trigger; a goodbye that leaves the
  traveler stranded on the immersive screen fails this scenario.
- [e2e-api] — verified with "That is all I have in me tonight" →
  `intake_complete` frame in the same turn.

### QA-10 Skip works and doesn't loop
- **When** the traveler leaves via the orange button under "the adventure,
  so far" (it reads "Skip for now" before anything is captured, "Open the
  journal" after; below lg the header keeps a quiet skip link)
- **Then** they land on the dashboard, and navigating around the trip does
  **not** bounce them back to `/new` in this browser session (skip marker),
  even though the brief may still be empty.
- [e2e-ui]

### QA-11 Same session, preserved conversation
- **Given** the traveler reached the dashboard via move-on or skip
- **Then** the concierge column resumes the **same** session (no new session
  row), the full intake conversation replays in the thread, and a new message
  continues it — now in planning mode, so the agent may propose cards again.
- [e2e-api] — session id stable across intake → dashboard scope; turn count
  grows on the same session.

## The empty journal after intake

### QA-12 Dated trip → real empty days
- **Given** intake captured exact dates (e.g. Sep 12–18)
- **Then** the dashboard journal renders the full day span with dates, each
  day an open/quiet day with the (+) insert affordance (editable — it's the
  traveler's fork).
- [unit] adapter/day-scaffold test

### QA-13 Undated trip → Day 1..7 default
- **Given** intake ended with no concrete dates (flexible, or skipped)
- **Then** the journal renders a 7-day scaffold ("Day 1" … "Day 7"); if
  `duration_nights` was captured, the scaffold length follows it instead.
- [unit] adapter test

### QA-14 The empty journal directs attention to the chat
- **Given** an empty (zero-card) journal on the traveler's fork
- **Then** instead of the flat "the journal is blank" placeholder, the empty
  state invites action: a line directing the traveler to Artemis with a CTA
  that opens/focuses the concierge column, alongside the day scaffold.
- [unit] render test / [e2e-ui]

## Regressions

### QA-15 Nothing else moved
- Full suites stay green: `pnpm -C apps/web test -- --run`, `pnpm typecheck`,
  `pnpm lint`, `uv run pytest -q`, `uv run ruff check .`, `uv run mypy`
  (apps/api), api-client regenerated & committed.
- Advisor intake form, basecamp chat, existing journal behavior with cards,
  fork/reconcile flows unchanged.
- [unit] + CI jobs
