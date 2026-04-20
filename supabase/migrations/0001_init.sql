-- 0001_init.sql
-- Initial schema for OV Black: profiles + invites with day-one RLS.
-- Owned by Supabase CLI (D003). SQLAlchemy reads/writes as a query layer only.

-- ── Enums ──────────────────────────────────────────────────────────────────
create type public.user_role as enum ('advisor', 'client');

-- ── Tables ─────────────────────────────────────────────────────────────────

-- profiles: 1:1 with auth.users, carries role + created_at.
-- The PK is the auth.users.id so a row only exists for a real Supabase user.
create table public.profiles (
    id          uuid primary key references auth.users (id) on delete cascade,
    role        public.user_role not null,
    created_at  timestamptz not null default now()
);

-- invites: one row per single-use invite code. consumed_at marks redemption.
-- created_by tracks the advisor who issued the invite (for audit).
create table public.invites (
    code         text primary key,
    role         public.user_role not null,
    email        text,
    consumed_at  timestamptz,
    created_by   uuid references auth.users (id) on delete set null,
    created_at   timestamptz not null default now()
);

create index invites_email_idx on public.invites (email) where email is not null;
create index invites_unconsumed_idx on public.invites (code) where consumed_at is null;

-- ── Row-Level Security ─────────────────────────────────────────────────────
-- Enabling RLS without a policy denies all access for anon/authenticated;
-- the service_role bypasses RLS entirely. That is the deliberate model:
-- profiles are readable by their owner, invites are service-role only.

alter table public.profiles enable row level security;
alter table public.invites  enable row level security;

-- profiles: owner-only read. No insert/update/delete policy — the API does
-- mutations via the service_role (which bypasses RLS).
create policy "profiles_owner_select"
    on public.profiles
    for select
    to authenticated
    using (auth.uid() = id);

-- invites: no policies for anon/authenticated. All access flows through
-- the service_role (FastAPI admin path). RLS-enabled-with-no-policy =
-- deny by default for non-service callers.
