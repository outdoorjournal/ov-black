-- 0022_fork_reconcile.sql
-- M004 Phase G3 — diff + reconcile (+ conversational fork), mvp-plan §3 / the G3 handoff.
--
-- G2 (0021) gave a fork lineage on every node (`forked_from_node_id`) and a
-- `fork_status` lifecycle (`open`/`reconciled`/`abandoned`). G3 adds the *request*
-- half of the reconcile flow: a traveler (or the agent on their behalf) cannot
-- merge a fork themselves — they can only ask staff to. Those asks are stamped on
-- the fork itinerary so an advisor's "forks awaiting review" list and the
-- itinerary view can surface them.
--
-- The diff itself is computed live from the two graphs (G2's lineage column) — no
-- new node columns. Reconcile mutates the live baseline through the existing
-- update_node/delete_node service path (so the G1 status gate keeps booked nodes
-- immutable); the only persisted G3 state is the request stamp here + the
-- `fork_status` transition G2 already modelled.
--
-- Additive only, both columns nullable (a fork with no pending request has them
-- NULL). Idempotent idiom matches 0014–0021 so a repeated `supabase db reset` is
-- safe.

-- ── 1. Reconcile-request stamp on public.itineraries ──────────────────
-- `reconcile_requested_at` is NULL until a traveler/agent requests a merge; it is
-- set by POST /itinerary/{fork}/request-reconcile and cleared on reconcile or
-- abandon. `reconcile_request_note` is the optional accompanying note ("I'd prefer
-- the slower Kyoto version"). Both live only on a fork row.
alter table public.itineraries
    add column if not exists reconcile_requested_at timestamptz;

alter table public.itineraries
    add column if not exists reconcile_request_note text;

-- ── 2. Index for the advisor "forks awaiting reconcile" list ──────────
-- Partial — only forks with a live request participate, so the advisor dashboard
-- lookup stays cheap.
create index if not exists itineraries_reconcile_requested_idx
    on public.itineraries (reconcile_requested_at)
    where reconcile_requested_at is not null;
