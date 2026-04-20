-- 0002_itinerary_graph.sql
-- Itinerary graph spine for M001/S02: itineraries + nodes + edges with an
-- append-only history table per mutating table, Postgres-native enums, and
-- deny-by-default RLS (same posture as invites in 0001_init.sql).
-- Owned by Supabase CLI (D003). SQLAlchemy reads/writes as a query layer only.

-- ── Enums ──────────────────────────────────────────────────────────────────
create type public.node_type as enum (
    'destination', 'flight', 'hotel', 'experience', 'meal',
    'transit', 'free_time', 'note'
);

create type public.node_status as enum (
    'idea', 'proposed', 'approved', 'booked', 'confirmed'
);

create type public.edge_type as enum (
    'follows', 'alternative_to', 'connected_by', 'requires', 'grouped_with'
);

-- ── Tables ─────────────────────────────────────────────────────────────────

-- itineraries: top-level container. One per client request. locked_by/locked_at
-- back R019 (advisor edit-lock); columns land here so S08 doesn't re-migrate.
create table public.itineraries (
    id          uuid primary key default gen_random_uuid(),
    client_id   uuid references auth.users (id) on delete set null,
    created_by  uuid references auth.users (id) on delete set null,
    title       text not null default '',
    locked_by   uuid references auth.users (id) on delete set null,
    locked_at   timestamptz,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now()
);

-- nodes: items in the graph. parent_subgraph_id is the self-FK for subgraphs
-- (PRD §10 Amalfi-tour case). Provenance columns are first-class (not buried
-- in metadata) so partial indexes can enforce lookup + uniqueness; the
-- nodes_provenance_complete check backs R020 at the schema level.
create table public.nodes (
    id                  uuid primary key default gen_random_uuid(),
    itinerary_id        uuid not null references public.itineraries (id) on delete cascade,
    parent_subgraph_id  uuid references public.nodes (id) on delete cascade,
    type                public.node_type   not null,
    status              public.node_status not null default 'idea',
    title               text not null default '',
    source              text,
    source_id           text,
    metadata            jsonb not null default '{}'::jsonb,
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now(),
    constraint nodes_provenance_complete
        check ((source is null and source_id is null)
            or (source is not null and source_id is not null))
);

-- edges: typed relationships. Deliberately NOT strictly acyclic — PRD §10
-- says alternative_to can form implicit sibling clusters.
create table public.edges (
    id            uuid primary key default gen_random_uuid(),
    itinerary_id  uuid not null references public.itineraries (id) on delete cascade,
    from_node_id  uuid not null references public.nodes (id) on delete cascade,
    to_node_id    uuid not null references public.nodes (id) on delete cascade,
    type          public.edge_type not null,
    metadata      jsonb not null default '{}'::jsonb,
    created_at    timestamptz not null default now(),
    constraint edges_no_self_loop check (from_node_id <> to_node_id)
);

-- node_history / edge_history: append-only. Written by the service layer in
-- the same transaction as the mutation (see S02 research "Decision: history
-- via service-layer writes, NOT triggers"). `before` is null on insert;
-- `after` is null on delete. actor_kind is required so a future agent can
-- reconstruct who made a change.
create table public.node_history (
    id             bigserial primary key,
    node_id        uuid not null,
    itinerary_id   uuid not null,
    op             text not null check (op in ('insert','update','delete')),
    actor_user_id  uuid,
    actor_kind     text not null,
    actor_id       text,
    before         jsonb,
    after          jsonb,
    occurred_at    timestamptz not null default now()
);

create table public.edge_history (
    id             bigserial primary key,
    edge_id        uuid not null,
    itinerary_id   uuid not null,
    op             text not null check (op in ('insert','update','delete')),
    actor_user_id  uuid,
    actor_kind     text not null,
    actor_id       text,
    before         jsonb,
    after          jsonb,
    occurred_at    timestamptz not null default now()
);

-- ── Indexes ────────────────────────────────────────────────────────────────
-- Names are load-bearing: tests and future migrations reference them by
-- identifier. Partial indexes mirror the invites_* idiom from 0001_init.sql.

create index nodes_itinerary_idx       on public.nodes (itinerary_id);
create index nodes_parent_subgraph_idx on public.nodes (parent_subgraph_id) where parent_subgraph_id is not null;
create index nodes_source_lookup_idx   on public.nodes (source, source_id) where source is not null;
create index nodes_status_idx          on public.nodes (itinerary_id, status);

create index edges_itinerary_idx on public.edges (itinerary_id);
create index edges_from_idx      on public.edges (from_node_id);
create index edges_to_idx        on public.edges (to_node_id);

create index node_history_node_idx on public.node_history (node_id, occurred_at desc);
create index edge_history_edge_idx on public.edge_history (edge_id, occurred_at desc);

-- ── Row-Level Security ─────────────────────────────────────────────────────
-- Day-one posture identical to invites in 0001: RLS enabled with ZERO
-- policies ⇒ anon/authenticated are denied. The FastAPI service_role bypasses
-- RLS and is the only writer. S03 may add auth.uid()-scoped read policies
-- when the advisor surface lands.

alter table public.itineraries  enable row level security;
alter table public.nodes        enable row level security;
alter table public.edges        enable row level security;
alter table public.node_history enable row level security;
alter table public.edge_history enable row level security;
