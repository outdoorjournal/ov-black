# Requirements

This file is the explicit capability and coverage contract for the project.

## Active

### R001 — Clients and advisors access Black only via an emailed magic-link tied to a pre-issued invite code. No self-serve signup.
- Class: launchability
- Status: active
- Description: Clients and advisors access Black only via an emailed magic-link tied to a pre-issued invite code. No self-serve signup.
- Why it matters: The product premise is invitation-only. Self-serve access would violate brand positioning and the pre-seeded Voodoo Doll flow that depends on advisor setup before first touch.
- Source: user
- Primary owning slice: M001/S01
- Supporting slices: none
- Validation: mapped
- Notes: Supabase Auth handles magic link + invite token validation.

### R002 — Advisor, in Command Center, creates a client record and hand-populates the full Voodoo Doll (passions, travel history, psychological triggers, party composition, constraints, deal-breakers, dream-trip signals) before sending the invite.
- Class: primary-user-loop
- Status: active
- Description: Advisor, in Command Center, creates a client record and hand-populates the full Voodoo Doll (passions, travel history, psychological triggers, party composition, constraints, deal-breakers, dream-trip signals) before sending the invite.
- Why it matters: Seeded Voodoo Doll is what lets the agent open from a position of attentiveness rather than discovery. The pre-invite flow is load-bearing; cold onboarding would break the craft premise.
- Source: user
- Primary owning slice: M001/S03
- Supporting slices: M001/S08
- Validation: mapped
- Notes: At scale (later milestones) this becomes auto-research; M001 is manual.

### R003 — The agent's first message is a specific, grounded observation derived from the seeded Voodoo Doll — not a generic greeting. This is the moment that either lands the magical first touch or misses.
- Class: differentiator
- Status: active
- Description: The agent's first message is a specific, grounded observation derived from the seeded Voodoo Doll — not a generic greeting. This is the moment that either lands the magical first touch or misses.
- Why it matters: Load-bearing craft moment. If this feels generic, every downstream investment is compromised.
- Source: user
- Primary owning slice: M001/S05
- Supporting slices: M001/S04
- Validation: mapped
- Notes: Success is judged in the final craft-feel sign-off.

### R004 — The agent adapts its approach based on how the client arrives: a client who names a dream trip gets oriented toward it immediately while the agent backfills Voodoo Doll gaps in the background; a vague client gets steered toward proposal through conversation. Seeded Voodoo Doll is the baseline; conversation validates and extends it.
- Class: primary-user-loop
- Status: active
- Description: The agent adapts its approach based on how the client arrives: a client who names a dream trip gets oriented toward it immediately while the agent backfills Voodoo Doll gaps in the background; a vague client gets steered toward proposal through conversation. Seeded Voodoo Doll is the baseline; conversation validates and extends it.
- Why it matters: PRD explicitly calls out "may have an upcoming dream trip in mind, but you may also need to pull it out of them." The agent must read the signal and pick the right mode, not interrogate.
- Source: user
- Primary owning slice: M001/S04
- Supporting slices: M001/S05
- Validation: mapped
- Notes: v1 rubric ships with M001; v2 emerges from watching real conversations.

### R005 — The background morphs based on conversation content (destinations, passions, mood) using hand-tuned named-mood palettes and a curated image library with Unsplash as fallback. The conversation surface itself — the panel holding agent prose — stays stable in color so text readability and craft rhythm are not disrupted by the morph.
- Class: differentiator
- Status: active
- Description: The background morphs based on conversation content (destinations, passions, mood) using hand-tuned named-mood palettes and a curated image library with Unsplash as fallback. The conversation surface itself — the panel holding agent prose — stays stable in color so text readability and craft rhythm are not disrupted by the morph.
- Why it matters: User explicitly emphasized the stability of the conversation surface while the frame around it breathes. The morph is living affect, not UI noise.
- Source: user
- Primary owning slice: M001/S06
- Supporting slices: M001/S05
- Validation: mapped
- Notes: Morph triggers on phase shifts (every 3–5 meaningful exchanges), not per message.

### R006 — As the agent proposes experiences during conversation, cards render in the side pane with real OV inventory: cover image, title, price, duration, difficulty, location, activities.
- Class: primary-user-loop
- Status: active
- Description: As the agent proposes experiences during conversation, cards render in the side pane with real OV inventory: cover image, title, price, duration, difficulty, location, activities.
- Why it matters: Cards must be backed by real inventory, not stubs, for the loop to feel live.
- Source: user
- Primary owning slice: M001/S07
- Supporting slices: M001/S02
- Validation: mapped
- Notes: OV is adapter #1 of many; the inventory abstraction (R009) ensures later providers plug in cleanly.

### R007 — Client interacts with mood-board cards via Must Do (pin), Thumbs Up (keep), Not This Time (discard). State persists across reloads and sessions.
- Class: primary-user-loop
- Status: active
- Description: Client interacts with mood-board cards via Must Do (pin), Thumbs Up (keep), Not This Time (discard). State persists across reloads and sessions.
- Why it matters: Signal for the agent and the advisor. Without persistence, cards are decorative.
- Source: user
- Primary owning slice: M001/S07
- Supporting slices: none
- Validation: mapped
- Notes: State flows back into the Voodoo Doll as refinement signal.

### R009 — Agent calls `search_inventory(kinds, filters)` and `get_inventory_detail(source, id)`. A provider registry dispatches to the right adapter. Each adapter normalizes to a common `InventoryItem` shape. OV is adapter #1; Duffel, Ratehawk, editorial partners land in later milestones without agent-prompt changes.
- Class: core-capability
- Status: active
- Description: Agent calls `search_inventory(kinds, filters)` and `get_inventory_detail(source, id)`. A provider registry dispatches to the right adapter. Each adapter normalizes to a common `InventoryItem` shape. OV is adapter #1; Duffel, Ratehawk, editorial partners land in later milestones without agent-prompt changes.
- Why it matters: PRD makes clear OV is one source of many. Baking provider knowledge into the agent means every new source becomes an agent-prompt refactor. Day-one abstraction is cheaper than later migration.
- Source: user
- Primary owning slice: M001/S02
- Supporting slices: M001/S07
- Validation: mapped
- Notes: Common `InventoryItem` shape lives in the graph schema as node metadata.

### R010 — AgentCore hosts the agent runtime (Claude via Bedrock), isolated session per client. Short-term scratchpad lives in AgentCore Memory within a session. Durable state — full turn log, proposed cards, graph mutations, pacing timers, Voodoo Doll refinements — writes to Postgres at turn boundaries so Command Center and future analytics can read it.
- Class: core-capability
- Status: active
- Description: AgentCore hosts the agent runtime (Claude via Bedrock), isolated session per client. Short-term scratchpad lives in AgentCore Memory within a session. Durable state — full turn log, proposed cards, graph mutations, pacing timers, Voodoo Doll refinements — writes to Postgres at turn boundaries so Command Center and future analytics can read it.
- Why it matters: Command Center must be able to read the agent's work without going through AgentCore's session API. Durable record also survives AgentCore outages and session expiry (8h cap).
- Source: user
- Primary owning slice: M001/S04
- Supporting slices: M001/S08
- Validation: mapped
- Notes: Long-term cross-session memory deferred to later milestone.

### R012 — Functional-before-fancy advisor dashboard. Queue of clients, open a client's session, view + edit Voodoo Doll, view + edit the draft itinerary graph, approve/release the gate. Client creation (R002) lives here.
- Class: primary-user-loop
- Status: active
- Description: Functional-before-fancy advisor dashboard. Queue of clients, open a client's session, view + edit Voodoo Doll, view + edit the draft itinerary graph, approve/release the gate. Client creation (R002) lives here.
- Why it matters: Without this, M001 has no advisor-facing half. The loop is client ↔ agent ↔ advisor; all three surfaces must exist.
- Source: user
- Primary owning slice: M001/S03
- Supporting slices: M001/S08
- Validation: mapped
- Notes: Timeline UI is functional, not polished; craft investment goes to the client surface.

### R014 — The client-facing surface holds the craft-feel line: no emoji in agent output, no loading spinners, no progress bars, single serif typeface for agent prose, slow-deliberate streaming as visible thinking.
- Class: quality-attribute
- Status: active
- Description: The client-facing surface holds the craft-feel line: no emoji in agent output, no loading spinners, no progress bars, single serif typeface for agent prose, slow-deliberate streaming as visible thinking.
- Why it matters: The entire product positioning. Breaking these makes Black feel like generic AI chat.
- Source: user
- Primary owning slice: M001 (enforced across all client-facing slices)
- Supporting slices: M001/S05, M001/S06, M001/S07, M001/S09
- Validation: mapped
- Notes: Enforced in the craft-feel sign-off gate (R021).

### R015 — The client sees the agent's first streamed token within ~2s of sending a message. The full response can stream over 10–30s — that slow-deliberate pacing is a feature. The failure mode is the silent dead zone before first token.
- Class: quality-attribute
- Status: active
- Description: The client sees the agent's first streamed token within ~2s of sending a message. The full response can stream over 10–30s — that slow-deliberate pacing is a feature. The failure mode is the silent dead zone before first token.
- Why it matters: Laggy feels broken; slow-deliberate feels crafted. The 2s first-token bound is the delineator.
- Source: user
- Primary owning slice: M001/S04
- Supporting slices: M001/S05
- Validation: mapped
- Notes: Measured under normal conditions (non-degraded Bedrock).

### R016 — Atmospheric morph transitions render at 60fps without jank. Image fades last 3–5s (weather, not UI). Text contrast over every palette shift stays at WCAG AA minimum.
- Class: quality-attribute
- Status: active
- Description: Atmospheric morph transitions render at 60fps without jank. Image fades last 3–5s (weather, not UI). Text contrast over every palette shift stays at WCAG AA minimum.
- Why it matters: Janky morph reads as broken, not atmospheric. Losing contrast mid-morph breaks readability and the craft line.
- Source: user
- Primary owning slice: M001/S06
- Supporting slices: none
- Validation: mapped
- Notes: Conversation surface remains stable-color; morph happens in the full-bleed frame around it (R005).

### R017 — Every FastAPI endpoint validates a Supabase-issued JWT before serving. Bedrock AgentCore runs with a scoped IAM role. All vendor secrets (OV API keys if any, Unsplash, Bedrock, Supabase service role) live in AWS Secrets Manager — never in committed env files.
- Class: compliance/security
- Status: active
- Description: Every FastAPI endpoint validates a Supabase-issued JWT before serving. Bedrock AgentCore runs with a scoped IAM role. All vendor secrets (OV API keys if any, Unsplash, Bedrock, Supabase service role) live in AWS Secrets Manager — never in committed env files.
- Why it matters: Ultra-wealthy clients. Security hygiene is non-negotiable.
- Source: user
- Primary owning slice: M001/S01
- Supporting slices: none
- Validation: mapped
- Notes: RLS policies on Postgres are an additional layer, defined in Supabase migrations.

### R018 — Transient agent/AgentCore/OV failures silent-retry with exponential backoff. If recovery fails, the client sees an honest, crafted message ("your concierge is stepping away for a moment") — never a stack trace, never a broken UI. Every failure logs to CloudWatch with session/turn/actor context.
- Class: failure-visibility
- Status: active
- Description: Transient agent/AgentCore/OV failures silent-retry with exponential backoff. If recovery fails, the client sees an honest, crafted message ("your concierge is stepping away for a moment") — never a stack trace, never a broken UI. Every failure logs to CloudWatch with session/turn/actor context.
- Why it matters: A luxury product must never feel fragile. Silent recovery when possible; honest disclosure when not.
- Source: user
- Primary owning slice: M001/S04
- Supporting slices: M001/S06, M001/S07
- Validation: mapped
- Notes: OV API failures treated by the agent as "no results in that direction right now" and conversation pivots.

### R020 — Every node in the itinerary graph that originated from an external inventory source carries `source` (e.g. `ov`) and `source_id` (the vendor's identifier). Downstream surfaces display attribution; future providers plug in without re-keying.
- Class: core-capability
- Status: active
- Description: Every node in the itinerary graph that originated from an external inventory source carries `source` (e.g. `ov`) and `source_id` (the vendor's identifier). Downstream surfaces display attribution; future providers plug in without re-keying.
- Why it matters: The graph must be portable across providers. Without provenance, switching or adding an inventory source becomes a migration.
- Source: inferred
- Primary owning slice: M001/S02
- Supporting slices: M001/S07
- Validation: mapped
- Notes: Node metadata field, not a separate table.

### R021 — M001 is not complete on mechanical checks alone. You run the full flow as the test client and as the advisor in staging, against real Bedrock and real OV API, and sign off explicitly on craft feel as a separate gate. Craft-feel failures (e.g. emoji slip, spinner appearing, morph breaking contrast, first-token delay) block completion regardless of test results.
- Class: launchability
- Status: active
- Description: M001 is not complete on mechanical checks alone. You run the full flow as the test client and as the advisor in staging, against real Bedrock and real OV API, and sign off explicitly on craft feel as a separate gate. Craft-feel failures (e.g. emoji slip, spinner appearing, morph breaking contrast, first-token delay) block completion regardless of test results.
- Why it matters: The entire product premise hinges on craft. Mechanical tests cannot verify "does it feel right."
- Source: user
- Primary owning slice: M001/S10
- Supporting slices: none
- Validation: mapped
- Notes: Both gates must pass: mechanical AND craft.

## Validated

### R008 — The itinerary graph is the spine. Postgres-native: `nodes` (destination / flight / hotel / experience / meal / transit / note), `edges` with typed relations (follows / alternative_to / connected_by / requires / grouped_with), subgraphs via nullable `parent_subgraph_id`, status enum (idea / proposed / approved / booked / confirmed), append-only `node_history` and `edge_history` with actor/timestamp/before/after on every mutation. Recursive CTEs for traversal.
- Class: core-capability
- Status: validated
- Description: The itinerary graph is the spine. Postgres-native: `nodes` (destination / flight / hotel / experience / meal / transit / note), `edges` with typed relations (follows / alternative_to / connected_by / requires / grouped_with), subgraphs via nullable `parent_subgraph_id`, status enum (idea / proposed / approved / booked / confirmed), append-only `node_history` and `edge_history` with actor/timestamp/before/after on every mutation. Recursive CTEs for traversal.
- Why it matters: Every downstream surface (client view, advisor Command Center, agent tools) reads from this graph. Getting the shape wrong here costs every later milestone.
- Source: user
- Primary owning slice: M001/S02
- Supporting slices: M001/S08
- Validation: S02 landed the graph spine (nodes/edges/history with append-only mutations + provenance CHECK). S08 closed the loop by adding the approval-state column (`status` enum, `approved_by`, `approved_at`) and the `assemble_initial_draft` composite that emits `follows` edges between consecutive proposed nodes in a DaySlot plan — with the same-transaction history discipline preserved (every edge INSERT writes a matching `edge_history` row). Validated end-to-end by the S08 six-bullet slice-acceptance suite + `test_itinerary_lock_routes.py::test_assemble_succeeds_...` + the race pytest.
- Notes: 10+ nodes with at least one subgraph is the M001 acceptance threshold.

### R011 — When the agent has assembled a full draft itinerary, it is held in a "draft" state visible only to the advisor in Command Center. Advisor reviews, edits, and approves. Only post-approval does the client see the final itinerary surface. Mood-board cards and onboarding chat responses are NOT gated — they surface live.
- Class: primary-user-loop
- Status: validated
- Description: When the agent has assembled a full draft itinerary, it is held in a "draft" state visible only to the advisor in Command Center. Advisor reviews, edits, and approves. Only post-approval does the client see the final itinerary surface. Mood-board cards and onboarding chat responses are NOT gated — they surface live.
- Why it matters: The PRD premise of "advisor reviews AI's work before it reaches the client" applies to the itinerary, not every turn. Gating turns would kill conversation liveness; not gating the itinerary would abandon the advisor's craft-guarantee role.
- Source: user
- Primary owning slice: M001/S08
- Supporting slices: M001/S09
- Validation: M001/S08 delivers: draft/approved status enum on `itineraries`; advisor-only `/lock`, `/release`, `/approve` routes; advisor-only draft-read admission (owning client, creator, or advisor); non-advisor GET on `status='draft'` returns 403 `{"detail":"forbidden"}`. Machine-checked by the six-bullet suite (`scripts/verify-s08.sh`), HTTP routes suite (`test_itinerary_lock_routes.py`, 18 cases), and the race-safety pytest.
- Notes: M001 ships the mechanism; internal demo may flag-disable for speed. Mechanism is not optional.

### R013 — After advisor approval, the client sees the full itinerary on a mobile-friendly web surface: day-by-day, typed sections (destinations, experiences, meals, transit, notes), source attribution on inventory nodes. Draft itineraries return 403 to the client.
- Class: primary-user-loop
- Status: validated
- Description: After advisor approval, the client sees the full itinerary on a mobile-friendly web surface: day-by-day, typed sections (destinations, experiences, meals, transit, notes), source attribution on inventory nodes. Draft itineraries return 403 to the client.
- Why it matters: The loop's close. Without a client-facing itinerary view, the product isn't demoable.
- Source: user
- Primary owning slice: M001/S09
- Supporting slices: none
- Validation: Validated by M001/S09. `/itinerary/[id]` renders the approved itinerary day-by-day with typed sections and `via Outdoor Voyage` attribution on OV-sourced nodes. Draft URLs collapse to notFound() via the S08 `GET /itinerary/{id}` 403 gate (existence-hiding preserved). Machine-checked by `scripts/verify-s09.sh` (6/6), `apps/web/tests/s09-slice-acceptance.test.tsx` (6/6 in vitest+RTL+jsdom), `apps/web/tests/dayChains.test.ts` (4/4 unit cases for the pure day-chain reconstruction helper), and the full vitest suite (9 files / 52 tests green). `apps/api` pytest stays at 270 passed (no API change). R014 craft-feel invariants asserted under `[data-testid='final-itinerary-view']`.
- Notes: PDF generation deferred (R058).

### R019 — When the advisor is editing a draft graph in Command Center, the graph is locked against agent writes. Agent-proposed mutations queue until the advisor releases. No last-writer-wins, no silent overwrites.
- Class: integration
- Status: validated
- Description: When the advisor is editing a draft graph in Command Center, the graph is locked against agent writes. Agent-proposed mutations queue until the advisor releases. No last-writer-wins, no silent overwrites.
- Why it matters: Without this the approval gate is unsafe — advisor edits could be clobbered by a concurrent agent turn.
- Source: user
- Primary owning slice: M001/S08
- Supporting slices: none
- Validation: M001/S08 delivers the lock-and-queue contract: per-itinerary in-memory FIFO in `_agent_write_queue` keyed on `itinerary_id`, `_persist_proposed_card` calls `_check_lock` before `add_node` and enqueues on LOCKED, `release_lock` triggers `drain_queue` via the router which clears `locked_by` first and replays through the normal service path. Validated by `test_itinerary_approval_race.py`: advisor lock + `asyncio.gather(_persist_proposed_card, update_node)` → agent write enqueues (queue_depth == 1), advisor commit succeeds, release drains (queue_depth == 0), `node_history` shows interleaved advisor + agent rows with correct actor_kind.
- Notes: Lock granularity is per-itinerary.

## Deferred

### R050 — Client ↔ concierge communication via WhatsApp, with the chat surface as an alternative to in-app.
- Class: integration
- Status: deferred
- Description: Client ↔ concierge communication via WhatsApp, with the chat surface as an alternative to in-app.
- Why it matters: PRD calls WhatsApp the primary channel for the ultra-wealthy demographic.
- Source: user
- Primary owning slice: M002
- Supporting slices: none
- Validation: unmapped
- Notes: Deferred to keep M001 to a single channel (in-app) and prove the loop.

### R051 — Client ↔ concierge via iMessage.
- Class: integration
- Status: deferred
- Description: Client ↔ concierge via iMessage.
- Why it matters: US-market demographic overlap with iMessage.
- Source: user
- Primary owning slice: M003+
- Supporting slices: none
- Validation: unmapped
- Notes: After WhatsApp; requires Apple Business Chat or a bridge.

### R052 — Braintree-backed deposit and final payment flows, initiated by advisor, completed by client.
- Class: core-capability
- Status: deferred
- Description: Braintree-backed deposit and final payment flows, initiated by advisor, completed by client.
- Why it matters: No bookings ship without payment.
- Source: user
- Primary owning slice: M002
- Supporting slices: none
- Validation: unmapped
- Notes: M001 stops at approved itinerary; booking and payment are the next loop.

### R053 — Encrypted document storage for passports, visas, loyalty numbers, traveler preferences — reusable across trips.
- Class: core-capability
- Status: deferred
- Description: Encrypted document storage for passports, visas, loyalty numbers, traveler preferences — reusable across trips.
- Why it matters: Friction elimination across the client's lifetime of travels.
- Source: user
- Primary owning slice: M002
- Supporting slices: none
- Validation: unmapped
- Notes: Requires encryption-at-rest design beyond Supabase Storage defaults.

### R054 — Flight search and booking via Duffel, as an inventory adapter.
- Class: integration
- Status: deferred
- Description: Flight search and booking via Duffel, as an inventory adapter.
- Why it matters: Flights are load-bearing for most itineraries.
- Source: user
- Primary owning slice: M002
- Supporting slices: none
- Validation: unmapped
- Notes: Plugs into the R009 provider abstraction.

### R055 — Hotel search and availability via Ratehawk, as an inventory adapter.
- Class: integration
- Status: deferred
- Description: Hotel search and availability via Ratehawk, as an inventory adapter.
- Why it matters: Hotel inventory breadth beyond OV curated trips.
- Source: user
- Primary owning slice: M002+
- Supporting slices: none
- Validation: unmapped
- Notes: Plugs into the R009 provider abstraction.

### R056 — Automated research pulls public signals (news mentions, social, public record, prior bookings) to pre-populate the Voodoo Doll before invite.
- Class: differentiator
- Status: deferred
- Description: Automated research pulls public signals (news mentions, social, public record, prior bookings) to pre-populate the Voodoo Doll before invite.
- Why it matters: Scales the "already knows you" effect beyond advisor hand-seeding.
- Source: user
- Primary owning slice: M003+
- Supporting slices: none
- Validation: unmapped
- Notes: Privacy/compliance review required before build.

### R057 — Cron-driven touchpoints: clarifying questions, expert-attributed progress updates, teaser cards, availability alerts, across hours and days.
- Class: primary-user-loop
- Status: deferred
- Description: Cron-driven touchpoints: clarifying questions, expert-attributed progress updates, teaser cards, availability alerts, across hours and days.
- Why it matters: "Necessary friction" as product principle — drip delivery is what makes the product feel bespoke.
- Source: user
- Primary owning slice: M002
- Supporting slices: none
- Validation: unmapped
- Notes: M001 does agent-paced output only (within-session). Scheduled out-of-session touchpoints come later.

### R058 — Mobile-friendly PDF export of the final itinerary.
- Class: admin/support
- Status: deferred
- Description: Mobile-friendly PDF export of the final itinerary.
- Why it matters: Clients expect a shareable, printable artifact.
- Source: user
- Primary owning slice: M002
- Supporting slices: none
- Validation: unmapped
- Notes: M001 ships web view only.

### R059 — Real advisor onboarding, queue assignment, handoffs between advisors, per-advisor queues.
- Class: operability
- Status: deferred
- Description: Real advisor onboarding, queue assignment, handoffs between advisors, per-advisor queues.
- Why it matters: Scaling beyond "advisor = you."
- Source: user
- Primary owning slice: M003+
- Supporting slices: none
- Validation: unmapped
- Notes: M001 supports one advisor (you).

### R060 — Cross-session continuous memory — the concierge remembers a client across months and trips, not just within an 8h session.
- Class: differentiator
- Status: deferred
- Description: Cross-session continuous memory — the concierge remembers a client across months and trips, not just within an 8h session.
- Why it matters: Black positions as "lifetime of travels." Without cross-session continuity, each return feels like a reset.
- Source: research
- Primary owning slice: M003+
- Supporting slices: none
- Validation: unmapped
- Notes: AgentCore Memory supports long-term primitives; integration requires a deliberate design pass.

### R093 — Nightly agent eval suite: cold-seeded / warm-seeded / meandering / impatient prompt suites scored by a rubric scorer, running on a nightly cadence (GitHub Actions cron or CloudWatch Scheduled Event), transcripts archived to S3 or equivalent. Deferred from M001/S10 per explicit scoping decision.
- Class: quality-attribute
- Status: deferred
- Description: Nightly agent eval suite: cold-seeded / warm-seeded / meandering / impatient prompt suites scored by a rubric scorer, running on a nightly cadence (GitHub Actions cron or CloudWatch Scheduled Event), transcripts archived to S3 or equivalent. Deferred from M001/S10 per explicit scoping decision.
- Why it matters: Named in M001 success criteria and context but intentionally deferred to M002 — R021 sign-off does not require automated nightly agent evaluation, and the eval suite is a substantial independent build (prompts + scorer + nightly job + archival) that would ~double S10 scope without advancing the craft-feel sign-off gate.
- Source: S10 planning + S10 research open question resolution
- Notes: milestone_target: M002. Defer rationale: R021 craft-feel sign-off is a human-scored rubric from a live walkthrough, not a nightly automated agent eval. The nightly suite is a separate observability/quality investment (prompt corpus, rubric scorer, nightly trigger, transcript archive) better scoped as its own M002 slice than bolted onto the M001 sign-off task. See .gsd/milestones/M001/slices/S10/CRAFT-RUBRIC.md 'Deferred Eval Suite Decision' block.

## Out of Scope

### R090 — Clients signing themselves up without CEO-issued invitation.
- Class: anti-feature
- Status: out-of-scope
- Description: Clients signing themselves up without CEO-issued invitation.
- Why it matters: Violates invitation-only positioning and breaks the pre-seeded Voodoo Doll flow.
- Source: user
- Primary owning slice: none
- Supporting slices: none
- Validation: n/a
- Notes: Permanent constraint, not a deferral.

### R091 — AI auto-books experiences/flights/hotels without advisor review and manual fulfillment.
- Class: anti-feature
- Status: out-of-scope
- Description: AI auto-books experiences/flights/hotels without advisor review and manual fulfillment.
- Why it matters: Humans are the safety net through MVP and beyond. Auto-booking risks brand damage that can't be undone.
- Source: user
- Primary owning slice: none
- Supporting slices: none
- Validation: n/a
- Notes: Out of scope through M001+; may be revisited much later.

### R092 — Reusing voyage-site's GraphQL schema, services, Drizzle models, or any runtime backend code.
- Class: constraint
- Status: out-of-scope
- Description: Reusing voyage-site's GraphQL schema, services, Drizzle models, or any runtime backend code.
- Why it matters: User explicitly chose fresh-build. voyage-site is reference for look-and-feel and integration patterns only.
- Source: user
- Primary owning slice: none
- Supporting slices: none
- Validation: n/a
- Notes: `doc/voyage-site-integrations.md` is reference material, not a build dependency. The OV public `/api/search` + `/api/trips/{id}` endpoints are consumed as any external HTTP API would be.

## Traceability

| ID | Class | Status | Primary owner | Supporting | Proof |
|---|---|---|---|---|---|
| R001 | launchability | active | M001/S01 | none | mapped |
| R002 | primary-user-loop | active | M001/S03 | M001/S08 | mapped |
| R003 | differentiator | active | M001/S05 | M001/S04 | mapped |
| R004 | primary-user-loop | active | M001/S04 | M001/S05 | mapped |
| R005 | differentiator | active | M001/S06 | M001/S05 | mapped |
| R006 | primary-user-loop | active | M001/S07 | M001/S02 | mapped |
| R007 | primary-user-loop | active | M001/S07 | none | mapped |
| R008 | core-capability | validated | M001/S02 | M001/S08 | S02 landed the graph spine (nodes/edges/history with append-only mutations + provenance CHECK). S08 closed the loop by adding the approval-state column (`status` enum, `approved_by`, `approved_at`) and the `assemble_initial_draft` composite that emits `follows` edges between consecutive proposed nodes in a DaySlot plan — with the same-transaction history discipline preserved (every edge INSERT writes a matching `edge_history` row). Validated end-to-end by the S08 six-bullet slice-acceptance suite + `test_itinerary_lock_routes.py::test_assemble_succeeds_...` + the race pytest. |
| R009 | core-capability | active | M001/S02 | M001/S07 | mapped |
| R010 | core-capability | active | M001/S04 | M001/S08 | mapped |
| R011 | primary-user-loop | validated | M001/S08 | M001/S09 | M001/S08 delivers: draft/approved status enum on `itineraries`; advisor-only `/lock`, `/release`, `/approve` routes; advisor-only draft-read admission (owning client, creator, or advisor); non-advisor GET on `status='draft'` returns 403 `{"detail":"forbidden"}`. Machine-checked by the six-bullet suite (`scripts/verify-s08.sh`), HTTP routes suite (`test_itinerary_lock_routes.py`, 18 cases), and the race-safety pytest. |
| R012 | primary-user-loop | active | M001/S03 | M001/S08 | mapped |
| R013 | primary-user-loop | validated | M001/S09 | none | Validated by M001/S09. `/itinerary/[id]` renders the approved itinerary day-by-day with typed sections and `via Outdoor Voyage` attribution on OV-sourced nodes. Draft URLs collapse to notFound() via the S08 `GET /itinerary/{id}` 403 gate (existence-hiding preserved). Machine-checked by `scripts/verify-s09.sh` (6/6), `apps/web/tests/s09-slice-acceptance.test.tsx` (6/6 in vitest+RTL+jsdom), `apps/web/tests/dayChains.test.ts` (4/4 unit cases for the pure day-chain reconstruction helper), and the full vitest suite (9 files / 52 tests green). `apps/api` pytest stays at 270 passed (no API change). R014 craft-feel invariants asserted under `[data-testid='final-itinerary-view']`. |
| R014 | quality-attribute | active | M001 (enforced across all client-facing slices) | M001/S05, M001/S06, M001/S07, M001/S09 | mapped |
| R015 | quality-attribute | active | M001/S04 | M001/S05 | mapped |
| R016 | quality-attribute | active | M001/S06 | none | mapped |
| R017 | compliance/security | active | M001/S01 | none | mapped |
| R018 | failure-visibility | active | M001/S04 | M001/S06, M001/S07 | mapped |
| R019 | integration | validated | M001/S08 | none | M001/S08 delivers the lock-and-queue contract: per-itinerary in-memory FIFO in `_agent_write_queue` keyed on `itinerary_id`, `_persist_proposed_card` calls `_check_lock` before `add_node` and enqueues on LOCKED, `release_lock` triggers `drain_queue` via the router which clears `locked_by` first and replays through the normal service path. Validated by `test_itinerary_approval_race.py`: advisor lock + `asyncio.gather(_persist_proposed_card, update_node)` → agent write enqueues (queue_depth == 1), advisor commit succeeds, release drains (queue_depth == 0), `node_history` shows interleaved advisor + agent rows with correct actor_kind. |
| R020 | core-capability | active | M001/S02 | M001/S07 | mapped |
| R021 | launchability | active | M001/S10 | none | mapped |
| R050 | integration | deferred | M002 | none | unmapped |
| R051 | integration | deferred | M003+ | none | unmapped |
| R052 | core-capability | deferred | M002 | none | unmapped |
| R053 | core-capability | deferred | M002 | none | unmapped |
| R054 | integration | deferred | M002 | none | unmapped |
| R055 | integration | deferred | M002+ | none | unmapped |
| R056 | differentiator | deferred | M003+ | none | unmapped |
| R057 | primary-user-loop | deferred | M002 | none | unmapped |
| R058 | admin/support | deferred | M002 | none | unmapped |
| R059 | operability | deferred | M003+ | none | unmapped |
| R060 | differentiator | deferred | M003+ | none | unmapped |
| R090 | anti-feature | out-of-scope | none | none | n/a |
| R091 | anti-feature | out-of-scope | none | none | n/a |
| R092 | constraint | out-of-scope | none | none | n/a |
| R093 | quality-attribute | deferred | none | none | unmapped |

## Coverage Summary

- Active requirements: 17
- Mapped to slices: 17
- Validated: 4 (R008, R011, R013, R019)
- Unmapped active requirements: 0
