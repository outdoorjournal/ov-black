-- 0014_travelgraph_schema_spine.sql
-- TravelGraph Phase 1 — schema spine.
--
-- Promotes time/location/role/branch-selection from `nodes.metadata` jsonb
-- conventions to first-class columns, splits the conflated `transit` type
-- into per-mode types (subway/train/drive/walk/boat) and adds `waiting` so
-- each card kind can carry its signature detail (Cards_Style_Guide.md);
-- introduces a `node_role` axis for graph-structural markers (destination
-- as subgraph anchor, terminus as subgraph end); adds a parties/travelers
-- model so per-party timelines, Meld, and Extract have a foundation; and
-- gives notes the dual-mode (attached vs. free-standing) shape called for
-- in the design doc.
--
-- Additive only. No drops of legacy `transit` / `destination` enum values
-- or columns — existing rows stay valid. Phase 2+ will start writing into
-- the new shape; this slice does not change service behavior.
--
-- Idempotent idiom matches 0005/0006/0011 so repeated `supabase db reset`
-- is safe.

-- ── 1. Extensions ──────────────────────────────────────────────────────
-- PostGIS gives us geography(Point/LineString) for first-class spatial
-- columns. Used by `nodes.location` and `nodes.route` below.
create extension if not exists postgis;

-- ── 2. New enum: node_role ────────────────────────────────────────────
-- Graph-structural axis — orthogonal to physical `node_type`. Linearization
-- skips rows where role is not null; renderers use them as headers / sync
-- points where divergent party tracks rejoin.
do $$
begin
    if not exists (
        select 1
          from pg_type t
          join pg_namespace n on n.oid = t.typnamespace
         where n.nspname = 'public'
           and t.typname = 'node_role'
    ) then
        create type public.node_role as enum ('destination', 'terminus');
    end if;
end$$;

-- ── 3. Extend node_type enum with the per-mode transit values + waiting ─
-- `transit` and `destination` remain valid for legacy rows; new code should
-- prefer the granular kinds. Each `add value if not exists` is metadata-
-- only and safe to re-run.
alter type public.node_type add value if not exists 'subway';
alter type public.node_type add value if not exists 'train';
alter type public.node_type add value if not exists 'drive';
alter type public.node_type add value if not exists 'walk';
alter type public.node_type add value if not exists 'boat';
alter type public.node_type add value if not exists 'waiting';

-- ── 4. New columns on public.nodes ────────────────────────────────────
-- All nullable / defaulted so existing rows stay valid. Order matters only
-- for readability; Postgres column order is stable across re-runs.

-- Time as a range, not a point. Early planning is fuzzy; firmness arrives
-- by collapsing the range. tstzrange `&&` makes overlap detection trivial
-- once Phase 5's analyzer wants it.
alter table public.nodes
    add column if not exists starts_at tstzrange;

-- Spatial point for fixed-location nodes (hotel, meal, experience, …).
alter table public.nodes
    add column if not exists location geography(Point, 4326);

-- Spatial line for traversal nodes (Shinkansen leg, hike, ferry).
alter table public.nodes
    add column if not exists route geography(LineString, 4326);

alter table public.nodes
    add column if not exists altitude_m integer;

-- Branch selection. Default true so non-alternative nodes (the vast
-- majority) act as "selected"; analyses fold over `where is_selected_alt`.
-- The renderer continues to display every alternative — this flag is
-- about which branch the analysis pass treats as the current plan.
alter table public.nodes
    add column if not exists is_selected_alt boolean not null default true;

-- Dual-mode notes: attached_to_node_id non-null → rides host's anchor;
-- null → free-standing note with its own starts_at. The XOR constraint in
-- §6 enforces the invariant. Cascade so deleting a host removes its
-- attached notes; free-standing notes are unaffected.
alter table public.nodes
    add column if not exists attached_to_node_id uuid
        references public.nodes (id) on delete cascade;

-- Graph-structural role (orthogonal to physical type). Null = ordinary.
alter table public.nodes
    add column if not exists role public.node_role;

-- ── 5. Backfill existing notes so the XOR constraint validates ────────
-- Pre-migration notes have neither attached_to_node_id nor starts_at; pick
-- the free-standing branch and anchor them at created_at as a degenerate
-- range. New writes (Phase 2+) will set one of the two fields explicitly.
update public.nodes
   set starts_at = tstzrange(created_at, created_at, '[]')
 where type = 'note'
   and attached_to_node_id is null
   and starts_at is null;

-- ── 6. Notes XOR constraint ───────────────────────────────────────────
-- For type='note' rows: exactly one of {attached_to_node_id, starts_at}
-- must be non-null. Non-note rows are unconstrained by this check.
do $$
begin
    if not exists (
        select 1 from pg_constraint
         where conname = 'notes_anchored_or_attached'
           and conrelid = 'public.nodes'::regclass
    ) then
        alter table public.nodes
            add constraint notes_anchored_or_attached check (
                type <> 'note'
                or (attached_to_node_id is null) <> (starts_at is null)
            );
    end if;
end$$;

-- ── 7. Indexes for the new shape ──────────────────────────────────────
-- GIST on starts_at unlocks `&&` overlap queries for the analyzer.
create index if not exists nodes_starts_at_idx
    on public.nodes using gist (starts_at)
    where starts_at is not null;

-- Spatial indexes — GIST is the natural fit for geography columns.
create index if not exists nodes_location_idx
    on public.nodes using gist (location)
    where location is not null;
create index if not exists nodes_route_idx
    on public.nodes using gist (route)
    where route is not null;

-- Lookup notes by host (the typical "show me notes attached to this card"
-- query). Partial — only attached notes have the FK set.
create index if not exists nodes_attached_to_idx
    on public.nodes (attached_to_node_id)
    where attached_to_node_id is not null;

-- Identify deselected branches cheaply — this is the unusual case worth
-- indexing because analyses skip them.
create index if not exists nodes_unselected_alt_idx
    on public.nodes (itinerary_id)
    where is_selected_alt is false;

-- Role lookups (terminus / destination) are tiny but partial keeps the
-- index hot for the renderer's header-strip query.
create index if not exists nodes_role_idx
    on public.nodes (itinerary_id, role)
    where role is not null;

-- ── 8. parties / travelers / node_parties ─────────────────────────────
-- Parties model the per-traveler timeline story (Meld, Extract). Default
-- behavior in Phase 2 will be a single "all" party per itinerary; explicit
-- multi-party itineraries split travelers across rows. Each `node_parties`
-- row says "this node belongs to this party's timeline."

create table if not exists public.parties (
    id              uuid primary key default gen_random_uuid(),
    itinerary_id    uuid not null references public.itineraries (id) on delete cascade,
    label           text not null default '',
    member_count    integer,
    attrs           jsonb not null default '{}'::jsonb,
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now()
);

create table if not exists public.travelers (
    id              uuid primary key default gen_random_uuid(),
    party_id        uuid not null references public.parties (id) on delete cascade,
    name            text not null default '',
    age             integer,
    profile_attrs   jsonb not null default '{}'::jsonb,
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now()
);

create table if not exists public.node_parties (
    node_id         uuid not null references public.nodes (id) on delete cascade,
    party_id        uuid not null references public.parties (id) on delete cascade,
    created_at      timestamptz not null default now(),
    primary key (node_id, party_id)
);

create index if not exists parties_itinerary_idx
    on public.parties (itinerary_id);
create index if not exists travelers_party_idx
    on public.travelers (party_id);
create index if not exists node_parties_party_idx
    on public.node_parties (party_id);

-- ── 9. RLS — deny by default, service_role bypasses ───────────────────
-- Same posture as itineraries / nodes / edges in 0002.
alter table public.parties      enable row level security;
alter table public.travelers    enable row level security;
alter table public.node_parties enable row level security;
