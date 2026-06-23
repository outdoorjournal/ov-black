-- 0003_clients_dossiers.sql
-- M001/S03: clients + dossiers with day-one RLS.
-- Typed-core + JSONB-long-tail split on dossiers per S03 research:
-- typed columns for stable signals S04's agent will ground on; JSONB for
-- evolving axes (passions, motivations, travel_history, …). Owned by Supabase
-- CLI (D003) — SQLAlchemy reads/writes as a query layer only.

-- ── Enums ──────────────────────────────────────────────────────────────────
create type public.group_type as enum (
    'solo', 'couple', 'family', 'friends', 'multigen', 'corporate'
);

create type public.contact_channel as enum (
    'email', 'sms', 'whatsapp', 'phone'
);

-- ── Tables ─────────────────────────────────────────────────────────────────

-- clients: an advisor-owned client record. owner_id is the advisor's auth.users
-- id (the advisor who created the client). auth_user_id is the client's own
-- auth.users id once they redeem the invite — populated by a later slice.
create table public.clients (
    id              uuid primary key default gen_random_uuid(),
    owner_id        uuid not null references auth.users (id) on delete cascade,
    auth_user_id    uuid references auth.users (id) on delete set null,
    full_name       text not null,
    email           text not null,
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now()
);

-- Per-advisor email uniqueness (case-insensitive). Two different advisors may
-- still each have a client with the same email.
create unique index clients_owner_email_idx
    on public.clients (owner_id, lower(email));

-- dossiers: 1:1 with clients (UNIQUE(client_id)). Typed columns capture
-- the stable signals; JSONB columns hold the evolving long-tail. authored_by
-- is the advisor who wrote the dossier (S03 always == clients.owner_id, but kept
-- explicit so future co-advising or hand-off flows do not require a migration).
create table public.dossiers (
    id                       uuid primary key default gen_random_uuid(),
    client_id                uuid not null references public.clients (id) on delete cascade,
    authored_by              uuid not null references auth.users (id) on delete cascade,
    contact_preference       public.contact_channel not null,
    group_type               public.group_type not null,
    children_ages            integer[] not null default '{}'::integer[],
    travel_party_notes       text not null default '',
    estimated_net_worth_usd  bigint,
    passions                 jsonb not null default '[]'::jsonb,
    motivations              jsonb not null default '{}'::jsonb,
    travel_history           jsonb not null default '[]'::jsonb,
    triggers                 jsonb not null default '[]'::jsonb,
    constraints              jsonb not null default '[]'::jsonb,
    deal_breakers            jsonb not null default '[]'::jsonb,
    dream_trip_signals       jsonb not null default '{}'::jsonb,
    osint_notes              jsonb not null default '{}'::jsonb,
    created_at               timestamptz not null default now(),
    updated_at               timestamptz not null default now(),
    constraint dossiers_client_id_unique unique (client_id)
);

-- ── Indexes ────────────────────────────────────────────────────────────────
-- Names are load-bearing: tests and future migrations reference them by
-- identifier. Pattern mirrors invites_*_idx / nodes_*_idx in 0001/0002.

create index clients_owner_idx   on public.clients (owner_id);
create index dossiers_author_idx on public.dossiers (authored_by);

-- ── Row-Level Security ─────────────────────────────────────────────────────
-- Day-one posture: owner-only SELECT for authenticated; ZERO insert/update/
-- delete policies. All mutations flow through the FastAPI service_role which
-- bypasses RLS entirely (D003 inherited from S01).

alter table public.clients  enable row level security;
alter table public.dossiers enable row level security;

create policy "clients_owner_select"
    on public.clients
    for select
    to authenticated
    using (auth.uid() = owner_id);

create policy "dossiers_owner_select"
    on public.dossiers
    for select
    to authenticated
    using (auth.uid() = authored_by);
