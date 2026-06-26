-- 0021_itinerary_fork.sql
-- M004 Phase G2 — itinerary fork (versioned clone), decision D-FORK (mvp-plan §6).
--
-- A fork is a versioned clone of an itinerary: a fresh `itineraries` row whose
-- `forked_from_id` points at the baseline, carrying a deep copy of the baseline's
-- nodes/edges. Pre-booked nodes copy in editable; `booked`/`confirmed` nodes copy
-- in carried-LOCKED (you cannot fork away a paid booking — the G1 status gate makes
-- a firmed node immutable wherever it lands). Every copied node records its origin
-- via `forked_from_node_id`, so the G3 diff/reconcile surface can pair fork↔baseline
-- nodes deterministically by lineage rather than by fuzzy matching.
--
-- In-graph `alternative_to` edges stay for *local* swaps (D-FORK keeps them); this
-- is whole-itinerary versioning, a different axis.
--
-- Additive only. All columns nullable: a normal (non-fork) itinerary has
-- `forked_from_id IS NULL` and `fork_status IS NULL`; a hand-built node has
-- `forked_from_node_id IS NULL`. Idempotent idiom matches 0014–0020 so a repeated
-- `supabase db reset` is safe.

-- ── 1. New enum: fork_status ──────────────────────────────────────────
-- The reconcile lifecycle of a fork (G3 drives the transitions): `open` (a fresh
-- fork, still diverging), `reconciled` (its accepted changes were folded back into
-- the baseline), `abandoned` (discarded without folding back). NULL on a baseline
-- itinerary — only forks carry a fork_status. Postgres-native ENUM per D020
-- (SQLAlchemy binds it with create_type=False — the migration owns the type).
do $$
begin
    if not exists (
        select 1
          from pg_type t
          join pg_namespace n on n.oid = t.typnamespace
         where n.nspname = 'public'
           and t.typname = 'fork_status'
    ) then
        create type public.fork_status as enum ('open', 'reconciled', 'abandoned');
    end if;
end$$;

-- ── 2. New columns on public.itineraries ──────────────────────────────
-- `forked_from_id` is the lineage to the baseline; ON DELETE SET NULL so a fork
-- survives its baseline being purged (it becomes a free-standing itinerary, not a
-- dangling FK). `fork_status` is NULL unless this row is a fork.
alter table public.itineraries
    add column if not exists forked_from_id uuid
        references public.itineraries (id) on delete set null;

alter table public.itineraries
    add column if not exists fork_status public.fork_status;

-- ── 3. New column on public.nodes ─────────────────────────────────────
-- `forked_from_node_id` is the per-node lineage: the baseline node this one was
-- copied from. ON DELETE SET NULL so editing/removing a baseline node doesn't
-- cascade-delete its forked descendant; the lineage simply goes null.
alter table public.nodes
    add column if not exists forked_from_node_id uuid
        references public.nodes (id) on delete set null;

-- ── 4. Indexes for lineage lookups ────────────────────────────────────
-- "list the forks of this itinerary" (G3 picker) and "pair this fork's nodes to
-- their origins" (diff). Partial — only fork rows / forked nodes participate.
create index if not exists itineraries_forked_from_idx
    on public.itineraries (forked_from_id)
    where forked_from_id is not null;

create index if not exists nodes_forked_from_node_idx
    on public.nodes (forked_from_node_id)
    where forked_from_node_id is not null;
