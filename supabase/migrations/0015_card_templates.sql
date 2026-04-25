-- 0015_card_templates.sql
-- TravelGraph Phase 4 — card-template (deck / library) layer.
--
-- A template is a reusable card or sub-graph an advisor can copy into
-- any client's itinerary. Templates store time as offsets from a "trip
-- start" anchor; instantiation receives a concrete trip_start_at and
-- materializes absolute tstzranges on the resulting nodes. Each
-- instantiated node carries template_id + template_version snapshots so
-- a future drift detector can flag "this template has been edited since
-- you used it" without ever silently rewriting an instantiated node.
--
-- Mirrors the public.nodes / public.edges shape so reasoning about a
-- template subgraph re-uses every Phase 1 invariant (the dual-mode notes
-- XOR, the no-self-loop edge check, the role axis). The legacy
-- nodes_provenance_complete check is intentionally NOT mirrored on
-- template_nodes — templates have their own provenance via card_templates.
-- Idempotent idiom matches 0014 so repeated `supabase db reset` is safe.

-- ── 1. card_templates ────────────────────────────────────────────────
-- One row per saved template. ``slug`` is the operator-facing handle
-- (path component / lookup key); ``version`` increments on each edit
-- and is what gets snapshotted onto every instantiated node.

create table if not exists public.card_templates (
    id                  uuid primary key default gen_random_uuid(),
    slug                text not null unique,
    name                text not null,
    description         text not null default '',
    version             integer not null default 1,
    owner_advisor_id    uuid references auth.users (id) on delete set null,
    metadata            jsonb not null default '{}'::jsonb,
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now()
);

create index if not exists card_templates_slug_idx
    on public.card_templates (slug);
create index if not exists card_templates_owner_idx
    on public.card_templates (owner_advisor_id)
    where owner_advisor_id is not null;

-- ── 2. template_nodes ────────────────────────────────────────────────
-- Mirrors public.nodes for every column the renderer / agent needs;
-- replaces tstzrange with a relative offset so the same template can
-- be instantiated against any trip_start_at.

create table if not exists public.template_nodes (
    id                              uuid primary key default gen_random_uuid(),
    template_id                     uuid not null
        references public.card_templates (id) on delete cascade,
    parent_id                       uuid
        references public.template_nodes (id) on delete cascade,
    attached_to_template_node_id    uuid
        references public.template_nodes (id) on delete cascade,
    type                            public.node_type not null,
    role                            public.node_role,
    title                           text not null default '',
    starts_at_offset_minutes        integer,
    duration_minutes                integer,
    altitude_m                      integer,
    is_selected_alt                 boolean not null default true,
    metadata                        jsonb not null default '{}'::jsonb,
    created_at                      timestamptz not null default now(),
    constraint template_notes_anchored_or_attached check (
        type <> 'note'
        or (attached_to_template_node_id is null)
            <> (starts_at_offset_minutes is null)
    )
);

create index if not exists template_nodes_template_idx
    on public.template_nodes (template_id);
create index if not exists template_nodes_parent_idx
    on public.template_nodes (parent_id)
    where parent_id is not null;
create index if not exists template_nodes_attached_idx
    on public.template_nodes (attached_to_template_node_id)
    where attached_to_template_node_id is not null;
create index if not exists template_nodes_role_idx
    on public.template_nodes (template_id, role)
    where role is not null;

-- ── 3. template_edges ────────────────────────────────────────────────
-- Mirror of public.edges. The no-self-loop check is repeated so the
-- template graph respects the same invariant.

create table if not exists public.template_edges (
    id                      uuid primary key default gen_random_uuid(),
    template_id             uuid not null
        references public.card_templates (id) on delete cascade,
    from_template_node_id   uuid not null
        references public.template_nodes (id) on delete cascade,
    to_template_node_id     uuid not null
        references public.template_nodes (id) on delete cascade,
    type                    public.edge_type not null,
    metadata                jsonb not null default '{}'::jsonb,
    created_at              timestamptz not null default now(),
    constraint template_edges_no_self_loop
        check (from_template_node_id <> to_template_node_id)
);

create index if not exists template_edges_template_idx
    on public.template_edges (template_id);
create index if not exists template_edges_from_idx
    on public.template_edges (from_template_node_id);
create index if not exists template_edges_to_idx
    on public.template_edges (to_template_node_id);

-- ── 4. Snapshot columns on public.nodes ──────────────────────────────
-- When a template is instantiated each new node remembers (a) which
-- template it came from, (b) which template_node was the source, and
-- (c) the template's version at the moment of copy. (b) lets us walk
-- back to the original for drift detection; (c) lets us answer "has
-- the template been edited since this instance was created?" without
-- comparing every field. Cascading the FK with ON DELETE SET NULL keeps
-- nodes alive if a template is purged — they simply lose their lineage.

alter table public.nodes
    add column if not exists template_id uuid
        references public.card_templates (id) on delete set null;

alter table public.nodes
    add column if not exists template_node_id uuid;

alter table public.nodes
    add column if not exists template_version integer;

create index if not exists nodes_template_idx
    on public.nodes (template_id)
    where template_id is not null;

-- ── 5. RLS — deny by default, service_role bypasses ──────────────────
-- Same posture as the rest of the graph tables (0002 / 0014).

alter table public.card_templates enable row level security;
alter table public.template_nodes enable row level security;
alter table public.template_edges enable row level security;
