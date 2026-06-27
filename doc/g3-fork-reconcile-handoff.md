# M004/G3 — Diff + Reconcile (+ conversational fork) — Handoff Plan

> **Status: NOT STARTED — this is an executable handoff.** G1 (status gates) and G2
> (versioned-clone fork) have landed on `dev` (commits `c06e871`, `e73a6a1`). This
> plan finishes M004: the staff diff/reconcile surface **plus** the conversational
> fork flow (agent works on the alternative and the traveler can request a merge).
>
> Companion docs: [mvp-plan.md](./mvp-plan.md) §8 (G1/G2 progress entries — read them
> first), [mvp.md](./mvp.md) Pillar 5. The e2e scaffold that lights up at the end of
> this slice already exists: `apps/cli/tests/e2e/test_pillar5_fork_reconcile_e2e.py::test_advisor_diffs_and_reconciles_a_fork`.

---

## 0. Locked decisions (founder)

1. **Reconcile authority — advisor executes; traveler requests.** Only an advisor
   merges accepted changes into the live plan (feasibility-gated), via the
   Command-Center UI **or** their private advisor agent session. A traveler can
   rework the alternative and *request* a merge; they cannot merge it themselves.
2. **Full-stack slice** — backend + agent + the Command-Center side-by-side diff
   view all ship in G3 (not a backend-first split).
3. **Session re-pins to the fork, persisted.** When the agent forks, the session
   moves onto the fork and stays there across turns. It is **very obvious** in the
   UI and conversation that we're on the alternative.
4. **The agent calls it "an alternative version," never "fork."** Internal/UI/API
   may say fork; the agent's *prose* says alternative.
5. **Booked/confirmed nodes are never changed via reconcile** — the G1 gate already
   enforces this because reconcile mutates the live graph through the same
   `update_node`/`delete_node` service path.

---

## 1. Acceptance (what "G3 done" means)

From [mvp-plan.md](./mvp-plan.md) G3 row + the fold-in:

- **Diff.** An advisor opens a fork's diff vs. its baseline — added / removed /
  changed / moved nodes, paired by `forked_from_node_id` lineage, side by side.
- **Feasibility gate.** Before accepting, the advisor runs Analyze (B5) on the
  fork; reconcile refuses (or warns + requires override) if accepted changes carry
  a `block` finding.
- **Reconcile.** Per-change accept/discard mutates the **live** (baseline) graph
  through the existing lock/queue + status-gate path; discarded changes stay only
  in the fork. A `booked` node can't be changed via reconcile. When resolved, the
  fork's `fork_status → reconciled` (or `abandoned`).
- **Conversational fork.** The agent forks → the session re-pins to the alternative
  → the agent reworks it (its mutation tools target the fork) and refers to it as
  "an alternative version." The traveler can **request** reconciliation; the advisor
  sees the pending request and executes it (UI or advisor agent).
- **Obvious UI.** The itinerary view shows an "alternative version of {baseline}"
  banner whenever `forked_from_id` is set.
- **e2e lights up.** `test_advisor_diffs_and_reconciles_a_fork` becomes a live
  assertion (drop the `flows.skip_until`).

Mechanical tests **and** a founder craft-feel pass gate completion (R021).

---

## 2. Architecture — three phases

```
Phase 1 (apps/api)         Phase 2 (apps/agent + apps/api)     Phase 3 (apps/web)
─────────────────────      ──────────────────────────────     ──────────────────────
diff_fork  ─────────────▶  fork-awareness in /agent/context    DiffPanel (side-by-side)
reconcile (advisor) ────▶  fork tool re-pins the session       "alternative version" banner
request-reconcile  ─────▶  request_reconcile (traveler tool)   accept/discard + run-Analyze
abandon                    reconcile_fork (advisor tool)        api-client wrappers
migration 0022             prompt: "alternative version"        store actions
```

Build **Phase 1 first and land it green** (it's the foundation), then Phase 2,
then Phase 3. Regenerate both SDKs once after Phase 1's schema is final (and again
if Phase 2 adds fields). Light up the e2e after Phase 1; extend it through 2/3.

---

## 3. Phase 1 — Backend: diff + reconcile

### 3.1 Migration `0022_fork_reconcile.sql`

Additive, idempotent (mirror `0021_itinerary_fork.sql` / the 0014–0021 idiom).
Apply locally with `psql "$LOCAL_DB_URL" -f supabase/migrations/0022_fork_reconcile.sql`
(`LOCAL_DB_URL = postgresql://postgres:postgres@127.0.0.1:54322/postgres`).

- `itineraries.reconcile_requested_at timestamptz` — null until a traveler requests
  a merge; set by request-reconcile, cleared on reconcile/abandon.
- `itineraries.reconcile_request_note text` — optional traveler/agent note ("I'd
  prefer the slower Kyoto version").
- (Optional) partial index `where reconcile_requested_at is not null` for the
  advisor "forks awaiting review" list.

No new node columns — the diff is computed from `forked_from_node_id` (already on
`nodes` from 0021). `fork_status` (0021) already has `open`/`reconciled`/`abandoned`.

Model edits ([app/models/itinerary.py](../apps/api/app/models/itinerary.py)
`Itinerary`): add `reconcile_requested_at` + `reconcile_request_note`. Surface them
on `ItineraryResponse` ([app/routers/itineraries.py](../apps/api/app/routers/itineraries.py))
+ `_itinerary_to_response`.

### 3.2 `services/fork.py::diff_fork`

Add to [app/services/fork.py](../apps/api/app/services/fork.py). Operates over two
`GraphView`s (reuse `get_itinerary_graph` for both) — no new SQL.

```python
@dataclass(frozen=True, slots=True)
class NodeChange:
    kind: str               # "added" | "removed" | "changed" | "moved"
    fork_node_id: uuid.UUID | None       # None for "removed"
    baseline_node_id: uuid.UUID | None   # None for "added"
    fields: tuple[str, ...]              # changed field names (for "changed")
    before: dict[str, Any] | None        # baseline snapshot
    after: dict[str, Any] | None         # fork snapshot

@dataclass(frozen=True, slots=True)
class ForkDiff:
    fork_id: uuid.UUID
    baseline_id: uuid.UUID
    added: list[NodeChange]
    removed: list[NodeChange]
    changed: list[NodeChange]
    moved: list[NodeChange]

async def diff_fork(session, *, fork_id) -> ForkDiff | ItineraryError: ...
```

**Algorithm** (pair fork→baseline by `forked_from_node_id`):

1. Load the fork itinerary; `NOT_FOUND` if missing; `VALIDATION_ERROR` if it has no
   `forked_from_id` (not a fork). Baseline = `fork.forked_from_id`.
2. `baseline_by_id = {n.id: n}`; `fork_origin = {n.forked_from_node_id: n for n if forked_from_node_id}`.
3. **removed**: every baseline node whose `id` is not in `fork_origin` (the fork
   deleted it).
4. **added**: every fork node with `forked_from_node_id is None` (created in the
   fork), *or* whose origin is absent from the baseline (origin deleted upstream).
5. For each paired (baseline B, fork F):
   - **changed**: compare `{title, type, status, cost_amount, cost_currency,
     cost_kind, starts_at, metadata, source, source_id}`. **Intrinsic-demotion
     rule:** ignore a status diff that is exactly `B.status==approved &&
     F.status==proposed` (that's G2's fork transform, not a user edit) — unless
     other fields differ, in which case record those fields and exclude `status`.
     Record the changed field names + before/after snapshots.
   - **moved**: compare graph position — the *origin-ids* of F's `follows`
     predecessor/successor (map fork neighbors back through `forked_from_node_id`)
     and F's `parent_subgraph_id` origin, vs. B's. If position differs, it's moved.
   - Keep `changed` and `moved` **disjoint**: if a node both changed content *and*
     moved, classify it `changed` and add a `"position"` entry to `fields` (so the
     UI can show one row). Pure-position-only → `moved`.
6. Return `ForkDiff`. Skip graph-structural roles (terminus/destination) the same
   way linearization does, if present.

Reuse the existing `_snapshot_forked_node`-style helper (or `_snapshot_node` from
itineraries) for before/after.

### 3.3 `services/fork.py::reconcile_fork` (advisor)

```python
@dataclass(frozen=True, slots=True)
class ReconcileDecision:
    change: NodeChange      # the change being acted on (or a stable change_id)
    accept: bool

async def reconcile_fork(
    session, actor, *, fork_id, decisions: list[ReconcileDecision],
    analysis_id: uuid.UUID | None = None, override_block: bool = False,
) -> Itinerary | ItineraryError: ...
```

**Flow** — mutate the **baseline** using the fork as the source of truth for each
accepted change, through the *existing* mutation service funcs (so the G1 gate +
history + lock all apply):

- **Feasibility gate** (before any mutation): resolve the fork's latest *completed*
  Analyze (or the passed `analysis_id`); if it has `block`-severity findings and
  `override_block` is false → return `ItineraryError(VALIDATION_ERROR, "fork_infeasible")`.
  (Reuse `services/analyze.get_analysis` / `list_analyses`; the fork carries geo
  because G2 copies PostGIS, so standard Analyze runs on it.)
- For each **accepted** decision, applied to the **baseline** itinerary:
  - `added` → `add_node(baseline_id, …fields from fork…)` (a new baseline node;
    leave `forked_from_node_id` null — it's now native to the live plan).
  - `removed` → `delete_node(baseline_id, baseline_node_id)` (G1: refused if the
    baseline node is booked → collect as a per-change failure, don't abort the whole
    batch).
  - `changed` → `update_node(baseline_id, baseline_node_id, **changed_fields)` (G1
    gate refuses booked; the demote-first rule stands).
  - `moved` → re-wire the baseline `follows` edges (delete/add) and/or `update_node`
    `starts_at` to match the fork's position.
- **discarded** decisions: no-op on the baseline (the change lives only in the fork).
- Stamp the fork `fork_status = reconciled` when every change is resolved
  (accepted-applied or discarded); leave `open` on a partial pass. Clear
  `reconcile_requested_at`.
- Return a result carrying the live graph + a per-change outcome list (applied /
  refused-booked / skipped) so the UI/agent can report honestly. Consider a typed
  `ReconcileResult { itinerary, applied: [...], refused: [...] }`.

**Authority:** the router gates `reconcile_fork` to advisors only (see 3.5). Don't
re-implement the booked-immutability check — let `update_node`/`delete_node` return
`STATUS_LOCKED` and surface it per-change.

### 3.4 `services/fork.py::request_reconcile` + `abandon_fork`

- `request_reconcile(session, actor, *, fork_id, note=None)` — owner/creator/advisor
  (reuse the `assert_itinerary_forkable` authority shape); stamps
  `reconcile_requested_at = now()` + `reconcile_request_note`. Idempotent.
- `abandon_fork(session, actor, *, fork_id)` — advisor or owner; `fork_status =
  abandoned`; clears the request. (A no-op write-path; the fork rows remain for
  audit.)

### 3.5 Router endpoints ([app/routers/itineraries.py](../apps/api/app/routers/itineraries.py))

Mirror the G2 fork endpoint's shape (`_load_itinerary` pre-load + authz helper +
`_raise_for_error`). All under the existing `/itinerary` prefix:

| Method & path | Auth | Body | Returns |
|---|---|---|---|
| `GET  /{fork_id}/diff` | owner/creator/advisor (`assert_itinerary_forkable`) | — | `ForkDiffResponse` |
| `POST /{fork_id}/reconcile` | **advisor only** (`require_advisor` + stamp ADVISOR) | `{decisions: [...], analysis_id?, override_block?}` | `ReconcileResponse` (live graph + per-change outcomes) |
| `POST /{fork_id}/request-reconcile` | owner/creator/advisor | `{note?}` | `ItineraryResponse` (with `reconcile_requested_at`) |
| `POST /{fork_id}/abandon` | advisor or owner | — | `ItineraryResponse` |

- Map a new `ItineraryOutcome` if needed (e.g. `NOT_A_FORK`, `FORK_INFEASIBLE`) or
  reuse `VALIDATION_ERROR` with a stable detail token. Keep the `_raise_for_error`
  switch exhaustive (mypy guards it).
- The advisor-gated reconcile uses `require_advisor` (not `require_user`), unlike
  fork/diff/request which are owner-or-advisor.
- A "forks awaiting reconcile" list for the advisor dashboard can piggyback on the
  existing advisor-itineraries route or add `GET /itineraries?reconcile_requested=1`
  — optional, Phase 3 may want it.

### 3.6 Phase-1 tests ([apps/api/tests/test_fork_reconcile.py](../apps/api/tests/))

- **diff (integration)**: build a baseline, fork it, then in the fork — edit a
  pre-booked node (→ changed), add a node (→ added), delete a node (→ removed),
  reorder follows edges (→ moved); assert each bucket. **Assert the intrinsic
  approved→proposed demotion is NOT reported as a change.**
- **reconcile (integration)**: accept a subset → baseline reflects only those;
  discard the rest → baseline unchanged for them; **a baseline booked node's change
  is refused (STATUS_LOCKED) and reported, not applied**; `fork_status → reconciled`.
- **feasibility gate**: a fork with a `block` finding refuses reconcile without
  `override_block`.
- **request/abandon**: stamps/clears `reconcile_requested_at`; `abandon` sets status.
- **router (stubbed)**: 200 diff, 201/200 reconcile, advisor-only 403 on reconcile,
  404 missing, 401 no JWT (mirror `test_fork.py::fork_routes` fixture + the
  `_load_itinerary`/authz monkeypatch pattern).
- `scripts/verify-sG3.sh` (mirror `verify-sG2.sh`) — one bullet per acceptance line.

---

## 4. Phase 2 — Agent: fork-awareness, re-pin, request/reconcile tools

Recon anchors (verify line numbers, they drift):
`app/models/agent.py` (`AgentSession.itinerary_id`), `app/services/agent.py`
(`open_or_reuse_session` re-pins `existing.itinerary_id` when a new `itinerary_id`
is passed; `stream_turn` builds `TurnPayload.itinerary_id` from the session row;
`_detect_mode`), `app/routers/agent_internal.py` (`GET /agent/context`),
`app/agent/traveler_context.py` (`assemble_traveler_context`),
`apps/agent/src/agent/backend.py` (`pin_ctx`), `apps/agent/src/agent/app.py`
(sets `pin_ctx` from `TurnPayload`), `apps/agent/src/agent/tools/` (+ bundles in
`tools/__init__.py`).

### 4.1 Re-pin the session to the fork (persisted)

The agent runtime reads its pinned itinerary per-turn from `pin_ctx`, which the API
sets from `agent_sessions.itinerary_id`. So **re-pin = update that column for the
current session**, and the *next* turn's `pin_ctx` is the fork.

**Recommended mechanism:** have the G2 fork tool ([apps/agent/.../tools/fork.py](../apps/agent/src/agent/tools/fork.py))
re-pin after creating the fork. Two implementable options:

- **(A, preferred) Re-pin via the existing session reuse path.** `open_or_reuse_session`
  already updates `agent_sessions.itinerary_id` when called with a new `itinerary_id`
  for the same `(client_id, audience)`. The fork tool POSTs `/sessions` with
  `{client_id (from pin_ctx), itinerary_id: fork_id, audience}`. **Caveat:** `pin_ctx`
  carries `client_id` + `actor_kind` but **not `audience`** today — thread `audience`
  into `TurnPayload` → `pin_ctx` (one field each in `schemas.py` + `app.py` + the
  API's payload builder in `stream_turn`) so the re-pin preserves the advisor vs
  traveler thread.
- **(B) A dedicated lightweight re-pin endpoint** `PATCH /sessions/{session_id}/itinerary`
  (agent-token-auth) that sets `itinerary_id`. Cleaner contract, one more endpoint;
  the fork tool needs the `session_id` (it's in the agent token claims —
  `app/services/agent_token.py`).

Either way: **within the same turn**, `pin_ctx` is still the baseline (it was set at
turn start), so a fork-then-immediately-mutate sequence in *one* turn still targets
the baseline. Mitigate by having the fork tool return a clear signal ("now working
on the alternative; changes apply from your next message") **or** have the fork tool
set `pin_ctx` in-process for the remainder of the turn too (set the ContextVar) — do
**both** (in-process set for the current turn + DB re-pin for future turns) for a
seamless feel. Document this in the tool docstring.

### 4.2 Fork-awareness in context + prompt

- Extend `GET /agent/context` (`AgentContext` schema in `app/schemas/facts.py`) and
  `stream_turn`'s context assembly: when the pinned itinerary has `forked_from_id`,
  add `is_alternative: bool`, `baseline_title: str | None`,
  `reconcile_requested: bool`.
- Extend `assemble_traveler_context(...)` to append a line when `is_alternative`:
  *"You are working on an ALTERNATIVE VERSION of '{baseline_title}', not the agreed
  plan. Refer to it as an alternative version. The traveler can ask you to request
  that staff merge it; you cannot merge it yourself."* Keep the redaction discipline
  (no net-worth/Dossier/OSINT in logs) unchanged.
- `_detect_mode`: a fork is `status=draft` → already resolves to **planning** mode
  (full editing tools), which is correct. No change needed; confirm with a test.

### 4.3 New agent tools (`apps/agent/src/agent/tools/`)

- **`request_reconcile(note: str | None = None)`** (traveler-facing; add to the
  **planning** bundle). Reads `pin_ctx.itinerary_id` (the fork); POSTs
  `/itinerary/{fork_id}/request-reconcile`. Docstring: "Ask staff to review and
  merge this alternative into the agreed plan. You cannot merge it yourself."
- **`reconcile_alternative(...)`** (advisor-facing; gate to the **advisor audience**
  only — see B7-audience work). Thin wrapper over `POST /{fork_id}/reconcile`. Given
  the per-change selection UX is awkward in chat, scope the agent tool to coarse
  actions first: "accept all feasible changes" / "discard the alternative"
  (`abandon`). Fine-grained accept/discard is the **UI's** job (Phase 3). Mark
  fine-grained agent reconcile as a follow-on if it proves needed.
- Register in `tools/__init__.py` bundles; mirror the `fork_itinerary`/`fill_gap`
  POST-wrapper pattern. The advisor-only tool should self-guard (the API enforces
  `require_advisor`; the tool surfaces the 403 honestly).

### 4.4 Phase-2 tests

- `apps/agent` offline: tool registration in the right bundles; the re-pin tool
  builds the right request; the advisor tool refuses for a traveler audience.
- `apps/api`: `/agent/context` carries `is_alternative`/`baseline_title` for a
  forked pin; `assemble_traveler_context` appends the alternative line;
  `open_or_reuse_session` re-pin path keeps audience.
- ovb e2e: extend pillar-5 — agent (or SDK) forks → re-pin observed on the next
  `/sessions` open → a traveler `request-reconcile` stamps the fork → advisor
  reconcile applies it. (Real agent turns need the local agent on :8080; the SDK
  path can stand in where the agent backend is dark.)

---

## 5. Phase 3 — Web: diff view + alternative banner

Recon anchors: `apps/web/app/itinerary/[id]/page.tsx` (RSC; resolves `canEdit`,
hands creds only to advisors), `apps/web/app/_components/itinerary-graph/views/horizontal/HorizontalView.tsx`
(the aside tab switcher Build/Concierge/Client/Party/Vault + panels stay mounted),
the store `…/store/itineraryGraphStore.tsx`, panel exemplars `AuthoringPanel.tsx` /
`PartyPanel.tsx` (api-client-in-`useEffect`, `{ok,…}` handling), styling tokens
(`shared/cards/tokens.tsx`, `CardShell.tsx`).

### 5.1 api-client wrappers ([packages/api-client/src/index.ts](../packages/api-client/src/index.ts))

Discriminated `{ok,…}` wrappers for the new routes: `getForkDiff`,
`reconcileFork`, `requestReconcile`, `abandonFork`. Re-export the generated
`ForkDiffResponse`/`ReconcileResponse`/`NodeChange` types. (The wrapper already
disambiguates `status_locked` on `updateNode` from G1 — reconcile's per-change
"refused-booked" comes back in the `ReconcileResponse` body, not a 409.)

### 5.2 "Alternative version" banner

Render in `HorizontalView` (just under the header, above the axis/canvas) whenever
`timeline.itinerary.forked_from_id` is set: *"You're viewing an alternative version
of {baseline title}."* + a link to the baseline + (advisor) a "Reconcile…" affordance
that opens the Diff tab. Craft: serif prose, no emoji/spinners, subtle stripe; use
`#8b2a1d` only if a destructive/attention accent is wanted. Dismiss state local to
the view. This is the "very obvious we're on the alternative" requirement.

### 5.3 Diff tab + `DiffPanel`

- Add `"diff"` to the aside tab array (advisor-only) in `HorizontalView`, mounted
  alongside the others (visibility-toggle pattern). Show it only when
  `forked_from_id` is set.
- `DiffPanel` (new, self-contained client component; follow `PartyPanel`): props
  `{ apiBaseUrl, accessToken, forkItineraryId, baselineItineraryId }`. On mount,
  `getForkDiff(api, forkItineraryId)` → render four sections (added / removed /
  changed / moved), each row showing before→after and an **Accept / Discard**
  toggle. A **"Run feasibility check"** button calls the existing `startAnalyze`
  (B7 store action) on the fork and shows findings (severity-sorted; block in
  `#8b2a1d`). A **"Reconcile selected"** button calls `reconcileFork(api, forkId,
  { decisions, analysis_id })` and renders the per-change outcome (applied /
  refused-booked) honestly — a booked refusal is expected, shown as "kept (booked)".
- Gate writes on the store's `selectEditable` (advisor + lock). Reconcile mutates
  the **baseline**, so after success, refresh the baseline graph (the panel may need
  the baseline's store or a refetch).
- Side-by-side: left = baseline node, right = fork node, per change. Reuse
  `NodeCard`/`CardShell` tokens for visual parity with the canvas.

### 5.4 Phase-3 tests

- vitest (`apps/web/tests/itineraryGraph/diff*.test.tsx`): DiffPanel renders the
  four buckets from a mocked `getForkDiff`; Accept/Discard toggles build the right
  `decisions`; Reconcile calls the wrapper and renders per-change outcomes incl. a
  booked "kept" row; the banner shows when `forked_from_id` is set and hides
  otherwise; travelers don't get the Diff tab.
- `apps/web` typecheck + `next lint` clean.

---

## 6. Cross-cutting: SDKs, invariants, e2e, docs

- **Regenerate both SDKs** after Phase 1 (and re-run after Phase 2 field adds):
  `pnpm -C packages/api-client generate` + `apps/cli/scripts/generate.sh`. The ovb
  `_generated/models.py` is **tracked** (commit it); api-client `src/generated/` is
  gitignored.
- **ovb hand-wrappers** (`apps/cli/src/ovb/sdk.py`): `fork_diff`, `reconcile_fork`,
  `request_reconcile`, `abandon_fork` (mirror `fork_itinerary`).
- **ovb invariants** (`apps/cli/src/ovb/invariants.py`): add `reconcile_holds(live,
  accepted, baseline)` — after reconcile, every *accepted* change is present in the
  live graph and every *discarded* change is absent; no booked node changed. The
  existing `status_actor_gate_holds` + `fork_lineage_holds` (G1/G2) already exist.
- **Light up the e2e**: `test_pillar5_fork_reconcile_e2e.py::test_advisor_diffs_and_reconciles_a_fork`
  — drop `flows.skip_until`, implement the intended flow already sketched in that
  file's docstring (fork → diff has changes → analyze_and_wait → reconcile subset →
  assert live graph reflects only accepted, booked unchanged). Add a fork-request +
  advisor-reconcile flow for the conversational half.
- **Docs**: flip the G3 row to ✅ in [mvp-plan.md](./mvp-plan.md); add a §8 progress
  entry (date · what landed · tested · remains); update [mvp.md](./mvp.md) Pillar 5
  (→ built) + the §3 summary table (Pillar 5 → fully built); update §7 next-steps
  (M005 is the remaining track). **With G3, M004 (Pillar 5) is complete.**

---

## 7. Build order & green gates

1. **0022 migration + models + diff_fork + GET /diff + diff tests** → `uv run pytest
   tests/test_fork_reconcile.py`, ruff, mypy green.
2. **reconcile + request + abandon + endpoints + tests** → full `apps/api` suite
   green (it was **664** after G2; this adds ~20–30).
3. **Regenerate SDKs; ovb wrappers + invariants; light up the e2e** (run the local
   API on :8000, `provision-local-users.sh`, `OVB_PROFILE=local`).
4. **Phase 2 agent** → `apps/agent` + `apps/api` suites green; agent offline tests.
5. **Phase 3 web** → api-client `tsc`, `apps/web` vitest + typecheck + lint green.
6. **verify-sG3.sh, docs, commit** (per-slice commit on `dev`, message style
   `feat(m004/g3): …`). Founder craft pass on the diff view + banner + the agent's
   "alternative version" prose.

Each phase commits independently if you prefer (the repo does per-slice commits);
Phase 1 is a clean standalone commit even if 2/3 land later.

---

## 8. Risks / open calls (decide while building)

- **`moved` precision.** Edge-neighbor diffing can be noisy on large reorders. Start
  with predecessor/successor origin-id comparison; if noisy, fall back to "position
  changed" as a single boolean per node and let the UI show it as a sub-flag of
  `changed`. Don't over-engineer move detection for the MVP.
- **Partial reconcile + re-diff.** After a partial accept, the fork still diverges;
  re-opening the diff should reflect the now-smaller delta (baseline moved). Make
  `diff_fork` always compute fresh from the two live graphs — never cache.
- **Same-turn fork-then-edit** (§4.1): set `pin_ctx` in-process for the current turn
  *and* re-pin the DB row, so the agent doesn't have to wait a turn to edit the
  alternative.
- **Feasibility gate strictness.** Founder call: hard-refuse on `block` vs.
  warn+`override_block`. Recommend **warn + explicit advisor override (logged)** so
  staff aren't dead-ended; default to refuse-without-override.
- **Advisor agent reconcile granularity** (§4.3): coarse ("accept all feasible" /
  "abandon") in G3; per-change accept/discard stays in the UI. Revisit if staff want
  conversational fine-grained reconcile.
- **Recon caveats.** The Explore passes that fed this doc approximated some line
  numbers and a couple of field names (e.g. client-ownership column); verify against
  source as you touch each seam. The schema facts (`agent_sessions.itinerary_id`,
  `fork_status` = open/reconciled/abandoned, `forked_from_node_id`) are confirmed.

---

## 9. File-touch checklist

**apps/api**: `supabase/migrations/0022_fork_reconcile.sql` · `app/models/itinerary.py`
· `app/services/fork.py` (diff_fork, reconcile_fork, request_reconcile, abandon_fork)
· `app/routers/itineraries.py` (4 endpoints + response models + outcome mapping) ·
`app/schemas/facts.py` (AgentContext fork fields) · `app/agent/traveler_context.py`
· `app/services/agent.py` (context assembly + audience in payload) ·
`tests/test_fork_reconcile.py` (+ extend `test_agent_*`).

**apps/agent**: `src/agent/tools/fork.py` (re-pin) · `src/agent/tools/request_reconcile.py`
(new) · `src/agent/tools/reconcile.py` (new, advisor) · `src/agent/tools/__init__.py`
· `src/agent/schemas.py` + `src/agent/app.py` + `src/agent/backend.py` (audience in
pin_ctx) · `tests/`.

**packages/api-client**: `src/index.ts` (4 wrappers) + regen `src/generated/`.

**apps/cli**: `src/ovb/sdk.py` (4 wrappers) · `src/ovb/invariants.py` (reconcile_holds)
· `src/ovb/_generated/models.py` (regen, tracked) · `tests/e2e/test_pillar5_fork_reconcile_e2e.py`
(light up + extend) · `tests/test_invariants.py`.

**apps/web**: `app/itinerary/[id]/page.tsx` (load baseline when forked) ·
`…/views/horizontal/HorizontalView.tsx` (banner + diff tab) · `…/views/horizontal/DiffPanel.tsx`
(new) · `…/store/itineraryGraphStore.tsx` (diff/reconcile actions if shared) ·
`tests/itineraryGraph/diff*.test.tsx`.

**scripts**: `verify-sG3.sh`. **docs**: `doc/mvp-plan.md`, `doc/mvp.md`.
