# Robin Thurston / Mt Olympus campaign demo

The inbound-campaign demo flow (article CTA → landing → campaign-aware intake →
dashboard skeleton build → reading list → advisor invoice). A campaign is
**data + config, not a forked code path**: everything runs through the ordinary
itinerary graph + agent turn loop; the "Olympus-ness" is a registry entry, a few
spine templates, a mood, and a seeded profile.

## What's built (and verified end-to-end against the local stack)

**Backend (`apps/api`)**
- `app/campaigns/registry.py` — the `Campaign` model + the `olympus` entry
  (title, brief, mood, opener, private `directive`, spine slugs by length,
  reading list). Facts are **seeded by hand**, not by the registry.
- Migrations `0046` (`node_type` += `article`), `0047` (`itineraries.campaign_id`
  + `mood`).
- `POST /demos/campaign/{id}` — traveler-self-serve seed of a shell itinerary
  (title + `campaign_id` + hero `mood`; no brief so intake still runs; no spine).
- `POST /itinerary/{id}/campaign/kickoff` — snaps the chosen nights to the
  nearest shipped spine (`services/campaign_spine.snap_length`) and lands it via
  `services/templates.instantiate_into` (5/7/14-night Olympus spines in
  `seed_data/olympus_itinerary.py` + `services/olympus_template.py`).
- `POST /itinerary/{id}/nodes/from-route` — a real, tier-aware ground transfer
  (`services/transfers.py` over the existing Google-Routes `compute_route`);
  persists a schedulable `drive` card with real geometry + `service_class` +
  vehicle. Survives a live "make it a taxi" change.
- `article` node kind: a first-class reading-list card. `save_link_to_collection`
  / `from-link` with `kind="article"` files it (OpenGraph preview + derived
  publication). `services/node_kinds.is_schedulable` derives `schedulable` (on
  `NodeResponse`); the write path refuses a `starts_at` on a non-schedulable card.
- Fork carries `campaign_id` + `mood` (so intake on the fork stays campaign-aware
  and the hero is right).

**Agent (`apps/agent`)**
- Campaign-awareness: `assemble_traveler_context(campaign_directive=…)` (API
  `services/agent._campaign_for_itinerary`) opens the agent grounded in Olympus —
  no forked prompt.
- Dashboard kickoff: a `surface="kickoff"` turn pins planning mode + appends
  `_campaign_kickoff_directive` (build spine → transfer → reading list → hand off).
- Tools: `assemble_campaign_spine`, `add_transfer` (tier + party aware),
  `save_link_to_collection` `kind="article"` — registered in the planning bundle.
  `olympus` mood added to `agent/moods.py` + `web/lib/atmos/moods.ts`.

**Web (`apps/web`)**
- `/campaign/[id]` landing (full-bleed mood hero + CTA) → `startCampaign` server
  action → `seedCampaign` (`packages/api-client`) → `/itinerary/{id}/new?campaign=…`.
- `schedulable` on the node model + `article` in the `NodeType` maps. Typecheck green.

**e2e + ops**
- `apps/cli/tests/e2e/test_olympus_demo_e2e.py` — deterministic scaffold
  (seed → snap 6→7 → spine → article → transfer → approve → invoice → pay),
  **passing** against the live stack.
- `apps/cli/tests/e2e/olympus_scenarios.json` — declarative `ovb agent eval`
  scenarios (kickoff build / reading list / tier-aware transfer). Assert
  tools/frames/diff, never wording. Needs the live agent (`scripts/restart-agent.sh`
  after any `apps/agent` edit).
- `scripts/seed-campaign.sh` — provisions the Robin client + hand-seeds the three
  fact tiers (flattering, non-creepy) and prints the `/campaign/olympus` link.

## Web wiring — now implemented (all three, typecheck + tests green)

1. **Dashboard auto-kickoff.** `ConciergeColumn` computes `autoKickoff =
   !canEdit && campaign_id && nodeCount === 0` and threads it through
   `SessionThread` → `ConciergeChat`, which fires ONE agent-first turn on mount
   (no visible user bubble) via a new per-call `sendTurn(content, {surface:
   "kickoff"})` override in `lib/agentStream.ts`. The kickoff endpoint is
   **idempotent** (no-op if the itinerary already has nodes) as a backstop.
2. **Intake opener.** `/itinerary/[id]/new` reads `?campaign` and passes the
   campaign opener (`lib/campaigns.ts`) to `IntakeExperience` via `seededOpener`
   (defaults to the generic line). Cosmetic — the agent is already Olympus-grounded
   via the server directive.
3. **Collection reading-list lane.** `article` gets its own "Reading list" lane
   (`collection/grouping.ts`); non-schedulable cards can't be dragged / placed
   (drag disabled + Place hidden, gated on `node.schedulable`); `note` cards are
   filtered out of the Collection (closes bugs.md "notes not needed in
   collection"). Article cards fall back to the snapshot (OpenGraph) render — a
   dedicated article card style is optional future polish.

## Cross-agent notes
- **Currency:** `transfers.py` stores a coarse **native EUR** estimate (Greece is
  Eurozone) and the demo invoice line is EUR. That's native-currency storage;
  display/normalization is the currency agent's concern.
- **Chat component:** the auto-kickoff + intake opener hooks land inside the chat
  component under refactor — integrate there.
