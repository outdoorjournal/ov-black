# Agent Parity — QA Scenarios (agent-behavior evals)

Area code: **AGT**. See [README.md](./README.md) for the scenario format and
status legend. The build plan that pairs with this file is
[advisor-plan.md](./advisor-plan.md) §6 **Wave C**.

> **This area is a different kind of scenario.** ONB/ITB/COL/ADV scenarios are
> browser-first: a person drives a screen, Playwright replays them, the API
> seam backstops. AGT scenarios have **no screen** — the subject under test is
> the *agent's behavior*: given a pinned plan and a natural-language ask, which
> tools does it fire, which SSE frames reach the wire, and what does the graph
> diff show? They are automated by the **Wave B eval harness**
> ([`ovb.evals`](../../apps/cli/src/ovb/evals.py)): each scenario is an
> `EvalScenario` (turn script + expected/forbidden tools + frame expectations +
> a graph-diff spec), run over the **real agent** (the founder's call: the mock
> lane carries no eval value — every eval drives live Bedrock turns).
>
> Consequences for how to read this file:
> - **Surface** is always the eval harness — `apps/cli/tests/e2e/`
>   `test_agent_eval_e2e.py` (`live_agent` pytest marker, run isolated /
>   `--workers=1`) and the same scenarios are drivable ad hoc via
>   `ovb agent eval`.
> - **Then bullets are structural invariants** (tool fired / graph diff /
>   frame emitted / a row at the API seam) — never wording. Semantic quality
>   is only ever checked by the opt-in LLM-judge rubric, and never gates.
> - **Honest skips are built in:** every eval self-skips on
>   `upstream_unavailable` (agent down / no Bedrock creds — e.g. an expired
>   `aws sso login --profile tov-sso`) and on a trace-less agent (running
>   without `EMIT_TOOL_TRACE=1`; `scripts/restart-agent.sh` sets it). A ✅
>   below means "green against live Bedrock when the gates are up", per the
>   date noted — live-model behavior is probabilistic, so a red eval is a
>   *signal to tune the rubric/tool docstrings*, not necessarily a product
>   regression.
> - The deterministic halves (tool request shapes, mode bundles, prompt
>   teaching, API seams) are pinned by ordinary unit tests, cited per
>   scenario alongside the eval.

## Coverage at a glance

| Scenario | Title | Status | Automated by (layer) |
| --- | --- | --- | --- |
| [AGT-1](#agt-1--the-agent-edits-a-cards-fields-in-place) | The agent edits a card's fields in place | ✅ Automated | `update_node_details` tool (`test_wave_c_tools`) + `node_updated` frame (`test_translate`) + eval `field-edit-in-place` (`test_agent_eval_e2e.py`) |
| [AGT-2](#agt-2--the-agent-knows-the-plans-state-without-being-asked-to-look) | The agent knows the plan's state without being asked to look | ✅ Automated | graph digest service (`test_graph_digest`) + prompt injection (`test_traveler_context`) + `/agent/context` field (`test_agent_internal_router`) + eval `digest-answers-plan-state` |
| [AGT-3](#agt-3--the-agent-answers-money-and-booking-questions-read-only) | The agent answers money + booking questions (read-only) | ✅ Automated | `billing`/`booking-state` routes + `derive_billing_state` (`test_billing_summary`) + tools (`test_wave_c_tools`) + eval `money-question-reads-billing` |
| [AGT-4](#agt-4--the-agent-escalates-to-the-human-advisor-thread) | The agent escalates to the human advisor thread | ✅ Automated | `POST /agent/thread-message` (`test_agent_internal_router`, `test_messaging` integration) + tool (`test_wave_c_tools`) + eval `escalate-to-advisor-thread` w/ API-seam backstop |

Pre-existing Wave B evals live here too in spirit — `analyze-conversational`
(ADV-6's live half) and `grounded-build-turn` (ADV-3's structural core) are in
the same eval module and follow the same rules.

---

## AGT-1 · The agent edits a card's fields in place

- **Status:** ✅ Automated (unit + live eval, green against live Bedrock 2026-07-08).
- **Personas:** Advisor ↔ Agent (client planning sessions carry the tool too)
- **Surface:** Agent eval harness + agent unit
- **Preconditions:** A pinned itinerary with editable (non-firmed) cards.
- **Automated by:**
  - `apps/cli/tests/e2e/test_agent_eval_e2e.py::test_agent_edits_a_card_in_place_with_the_field_editor` — eval `field-edit-in-place`.
  - `apps/agent/tests/test_wave_c_tools.py` — the PATCH body per field, the metadata read-merge-write (description/confirmation survive `start_time`/`snapshot`), the both-or-neither cost guard, unpinned/unknown-node guards.
  - `apps/agent/tests/test_translate.py::test_tool_result_update_node_details_maps_to_node_updated` — the browser refresh frame.
  - `apps/agent/tests/test_modes.py` — planning-bundle membership (not onboarding, not Q&A) + rubric teaching.

**Given** a pinned plan and a card whose substance is wrong or incomplete,

**When**
1. the user asks for an in-place edit ("set that dinner to 400 USD total",
   "give the ryokan card a description", "record confirmation # PNR123 on the
   villa I booked by phone");
2. the agent calls ``update_node_details`` with only the changed fields.

**Then**
- ``update_node_details`` fires — not ``propose_card`` (no re-create) and not
  ``update_node_status`` (no status flip);
- a ``node_updated`` frame reaches the wire, so an open board re-renders the card;
- metadata merges (existing ``start_time``/``snapshot`` keys survive), and a
  price lands only as a complete amount+currency pair;
- the G1 status×actor gate still holds server-side: a firmed card refuses the
  edit (``status_locked`` / ``demote_before_edit``) and the tool's docstring
  teaches the demote-first dance rather than a silent retry.

**Notes**
- This is the agent-side twin of ADV-13's card-detail **Edit facet** — same
  field set (title · description · cost trio · confirmation #), same server
  gates; a pasted-link card can now be priced conversationally too.
- Clearing a price (both-null) is deliberately not exposed in v1 of the tool.
- 🔎 **Learned tuning it live:** the Japan demo seeds mostly *firmed* cards
  (24/26 approved/booked/confirmed), which correctly refuse field edits behind
  the G1 gate — the first eval run failed exactly there. The eval now seeds
  one fresh `proposed` card and aims the edit at it: the gate is P5's subject;
  this scenario's is the editor.

---

## AGT-2 · The agent knows the plan's state without being asked to look

- **Status:** ✅ Automated (unit + live eval, green against live Bedrock 2026-07-08).
- **Personas:** Advisor ↔ Agent and Traveler ↔ Agent (every pinned session)
- **Surface:** Agent eval harness + API unit
- **Preconditions:** A session pinned to an itinerary.
- **Automated by:**
  - `apps/cli/tests/e2e/test_agent_eval_e2e.py::test_agent_answers_plan_state_from_the_digest_without_a_graph_read` — eval `digest-answers-plan-state` (**forbids** `get_itinerary` — the tool burn the digest exists to remove).
  - `apps/api/tests/test_graph_digest.py` — the rendered block: per-status propose-flow hints, lifecycle-ordered card counts (+ locked note), per-currency totals with party size, invoiced/uninvoiced lines only when non-zero, the pending-reconcile and blocking-findings lines.
  - `apps/api/tests/test_traveler_context.py` — the digest rides after the trip brief, before the private tiers; omitted when unpinned.
  - `apps/api/tests/test_agent_internal_router.py` — `GET /agent/context` mirrors it as `graph_digest`.

**Given** a pinned itinerary in any lifecycle state,

**When**
1. any turn starts (the API assembles the system prompt fresh — the digest is
   computed per turn and **replaces** the previous turn's copy, never stacks);
2. the user asks something the digest already answers ("where does the plan
   stand?", "how many cards are approved?", "what's the total?").

**Then**
- the system prompt carries one current "Live plan state" block: itinerary
  status **with its ADV-10 meaning** (draft → propose → approve is taught in
  the rubric), node counts by status, per-currency totals, the uninvoiced
  remainder, a pending reconcile request, and the latest analysis' block/warn
  counts;
- the agent answers a state question **without** calling ``get_itinerary``;
- the graph is untouched (a status question is never a write).

**Notes**
- Design decision (founder, 2026-07-08): **inject per turn** rather than make
  the agent fetch — cheaper than a tool round-trip and impossible to forget;
  no stacking because the prompt is rebuilt each turn. `get_traveler_context`
  returns the same block for a mid-turn refresh.
- The digest is also the substrate for AGT-4's opening-of-turn convention —
  the rubric tells the agent to flag material changes it shows before
  answering.
- 🔎 **Harness nuance this scenario forced:** a forbid-only turn with zero
  tool calls is indistinguishable, turn-locally, from a traceless agent — so
  `_check_tools` now hard-fails on an empty trace only when tools are
  *expected*, and this scenario runs **two turns**: turn 1 fires
  `get_billing_state` (proving the trace channel live), turn 2 asks the state
  question with `get_itinerary` forbidden. A traceless agent still skips via
  `EvalReport.trace_available`.

---

## AGT-3 · The agent answers money and booking questions (read-only)

- **Status:** ✅ Automated (unit + live eval, green against live Bedrock 2026-07-08).
- **Personas:** Advisor ↔ Agent; Traveler ↔ Agent (Q&A mode carries both reads)
- **Surface:** Agent eval harness + API unit
- **Preconditions:** A pinned itinerary with priced/approved (or booked) cards; optionally invoices.
- **Automated by:**
  - `apps/cli/tests/e2e/test_agent_eval_e2e.py::test_agent_reads_billing_state_for_a_money_question` — eval `money-question-reads-billing` (mutating tools forbidden; graph diff `no_change`).
  - `apps/api/tests/test_billing_summary.py` — `derive_billing_state`, the server-side port of the ADV-11 cockpit's `reconcileBilling`: remainder math, reversed-charge fallthrough, `per_person` × party expansion, void-invoice dropout, issued/paid rollup, approved-only chargeability.
  - `apps/agent/tests/test_wave_c_tools.py` — `get_billing_state` → `GET /itinerary/{id}/billing`, `get_booking_state` → `GET /itinerary/{id}/booking-state`, unpinned guards.
  - `apps/agent/tests/test_modes.py` — both reads in planning **and** Q&A bundles ("am I paid up?" is classic Q&A); rubric teaching in both.

**Given** a trip with money state (priced cards, maybe invoices/bookings),

**When**
1. the user asks a money question ("what's still unbilled?", "what do we
   owe?") or a booking question ("is the hotel confirmed?", "what's the
   confirmation number?", "is that flight price still held?");
2. the agent calls ``get_billing_state`` / ``get_booking_state``.

**Then**
- the right read fires and **no mutation ever does** — the human-in-the-loop
  boundary is structural (the tools are GETs; invoicing/booking execute in the
  advisor cockpit through the money gate);
- the billing read carries the same money truth as the advisor's
  reconciliation strip (per-currency trip total vs invoiced/paid/outstanding +
  the per-node uninvoiced remainder), so the agent can also *explain* a money-
  gate refusal ("that card isn't paid yet, so it can't book");
- the booking read quotes recorded supplier confirmation numbers and flags an
  expired held offer — quoted, never invented (the Q&A rubric's standing rule).

**Notes**
- The new routes (`/billing`, `/booking-state`) use the invoice read gate
  (advisor / owning client / creator), so both audiences' JWTs work; they're
  general API surface the web could adopt later (today the cockpit still
  derives client-side).
- Live Duffel offer expiry is creds-gated as ever (§4 posture in
  [advisor.md](./advisor.md)); the eval doesn't depend on a live offer.

---

## AGT-4 · The agent escalates to the human advisor thread

- **Status:** ✅ Automated (unit + integration + live eval w/ API-seam backstop, green against live Bedrock 2026-07-08).
- **Personas:** Traveler ↔ Agent → Advisor (and advisor-directed notes to the traveler)
- **Surface:** Agent eval harness + API seam + API unit/integration
- **Preconditions:** A session (pinned trip thread, or basecamp scope when unpinned).
- **Automated by:**
  - `apps/cli/tests/e2e/test_agent_eval_e2e.py::test_agent_escalates_to_the_human_thread` — eval `escalate-to-advisor-thread`, backstopped at the API seam: an `artemis`-authored message actually lands on the scope's human thread (read back via `POST /threads` + `GET /threads/{id}/messages`).
  - `apps/api/tests/test_agent_internal_router.py` — `POST /agent/thread-message` auth matrix: agent-token-only, 201 with `author_kind=artemis` + `author_id=None`, failures collapse to 404, empty content 422.
  - `apps/api/tests/test_messaging.py` (`@integration`) — `post_agent_thread_message` get-or-creates the same thread the humans use (the advisor sees the escalation on their existing surface) and refuses a foreign itinerary.
  - `apps/agent/tests/test_wave_c_tools.py` + `test_modes.py` — the tool posts the agent-internal route; present in planning + Q&A, taught in both rubrics.

**Given** a request only a human can fulfil (a booking change, a payment
action, a bespoke arrangement) — or plan state worth flagging,

**When**
1. the user asks the agent to loop in the advisor (or the agent judges it
   must); the agent calls ``post_thread_message`` with a short, specific note;
2. the advisor opens the trip's existing human thread.

**Then**
- exactly one message lands on the **same** thread the ADV-7/ADV-8 human
  channel uses (get-or-created for the scope) — no parallel store;
- it is attributed ``author_kind = artemis`` with no human author id, pinned
  **server-side** (the agent cannot impersonate the traveler or advisor);
- the graph is untouched — escalation is never a graph write;
- the disclosure invariant holds: the thread is traveler-visible, so
  Dossier/OSINT content must never appear in an escalation (same rule as
  every traveler-audience surface; the tool docstring restates it).

**Notes**
- The **opening-of-turn convention** is the proactivity half: the planning
  rubrics instruct the agent to open its reply by flagging material changes
  the live plan state shows (pending merge request, blocking finding, money
  newly outstanding). That's a prompt-level convention measured by the judge
  rubric when wanted — deliberately not gated structurally (wording-adjacent).
- Advisor notification beyond the thread itself (badge/feed) is **Wave D**
  (ADV-14, the awareness layer); email stays 🔍 per §4.

---

## Where these land in the suite

The four evals + the two Wave B evals live in
`apps/cli/tests/e2e/test_agent_eval_e2e.py` (marker `live_agent`; run isolated
against the local stack with the agent restarted via
`scripts/restart-agent.sh` so `EMIT_TOOL_TRACE=1` is on). The same scenarios
can be expressed as JSON for `ovb agent eval scenarios.json --client-id …`
when tuning prompts by hand. Deterministic halves (request shapes, bundles,
prompts, seams) run in the ordinary `apps/agent` / `apps/api` unit suites and
CI.
