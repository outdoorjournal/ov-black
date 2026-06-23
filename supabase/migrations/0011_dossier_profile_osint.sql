-- 0011_dossier_profile_osint.sql
-- Split the dossier's long-tail into three semantically distinct fact
-- stores with explicit disclosure rules:
--   * dossiers: private internal knowledge, typed core only. Long-tail
--     JSONB sections move to dossier_facts.
--   * dossier_facts: per-fact rows for advisor-seeded long-tail and
--     agent-inferred private observations. NEVER revealed to traveler.
--   * profile_facts: per-fact rows for things the traveler self-expressed.
--     MAY be referenced naturally in agent conversation.
--   * osint_facts: per-fact rows for external research (LinkedIn, press,
--     etc.). NEVER revealed to traveler.
--
-- Every fact row carries provenance via source_kind, soft-deletes via
-- redacted_at/by/reason, and an observed_at timestamp so the command
-- center can show "what we learned and when". A per-table CHECK
-- constraint pins the legal source_kind values for that tier.
--
-- RLS posture matches existing tables: owner-only SELECT for the calling
-- advisor; mutations bypass via FastAPI's service_role.

-- ── 1. dossiers table ─────────────────────────────────────────────────
-- The typed-core dossiers table (with its index, unique constraint, and
-- owner-only RLS) is created in 0003_clients_dossiers.sql. This migration
-- only adds the per-fact stores below and moves the long-tail JSONB into
-- them, then drops those columns from dossiers (section 8).

-- ── 2. New enums for fact source_kind + per-tier kinds ────────────────
create type public.fact_source_kind as enum (
    'advisor', 'agent_inferred', 'traveler_told', 'scraper'
);

create type public.dossier_fact_kind as enum (
    'passion','motivation','travel_history','trigger','constraint',
    'deal_breaker','dream_signal','party','preference','other'
);

create type public.profile_fact_kind as enum (
    'passion','motivation','travel_history','trigger','constraint',
    'deal_breaker','dream_signal','preference','aspiration','other'
);

create type public.osint_fact_kind as enum (
    'linkedin','facebook','instagram','press','company','public_record','other'
);

-- ── 3. dossier_facts ──────────────────────────────────────────────────
create table public.dossier_facts (
    id              uuid primary key default gen_random_uuid(),
    client_id       uuid not null references public.clients (id) on delete cascade,
    kind            public.dossier_fact_kind not null,
    text            text not null check (length(text) between 1 and 4000),
    source_kind     public.fact_source_kind not null,
    source_ref      jsonb not null default '{}'::jsonb,
    observed_at     timestamptz not null default now(),
    recorded_by     uuid not null,
    redacted_at     timestamptz,
    redacted_by     uuid,
    redacted_reason text,
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now(),
    constraint dossier_facts_source_kind_valid
        check (source_kind in ('advisor','agent_inferred'))
);

create index dossier_facts_client_active_idx
    on public.dossier_facts (client_id, observed_at desc)
    where redacted_at is null;
create index dossier_facts_client_kind_idx
    on public.dossier_facts (client_id, kind)
    where redacted_at is null;
create index dossier_facts_session_idx
    on public.dossier_facts ((source_ref->>'session_id'))
    where redacted_at is null;

-- ── 4. profile_facts ──────────────────────────────────────────────────
create table public.profile_facts (
    id              uuid primary key default gen_random_uuid(),
    client_id       uuid not null references public.clients (id) on delete cascade,
    kind            public.profile_fact_kind not null,
    text            text not null check (length(text) between 1 and 4000),
    source_kind     public.fact_source_kind not null,
    source_ref      jsonb not null default '{}'::jsonb,
    observed_at     timestamptz not null default now(),
    recorded_by     uuid not null,
    redacted_at     timestamptz,
    redacted_by     uuid,
    redacted_reason text,
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now(),
    constraint profile_facts_source_kind_valid
        check (source_kind in ('traveler_told','advisor'))
);

create index profile_facts_client_active_idx
    on public.profile_facts (client_id, observed_at desc)
    where redacted_at is null;
create index profile_facts_client_kind_idx
    on public.profile_facts (client_id, kind)
    where redacted_at is null;
create index profile_facts_session_idx
    on public.profile_facts ((source_ref->>'session_id'))
    where redacted_at is null;

-- ── 5. osint_facts ────────────────────────────────────────────────────
create table public.osint_facts (
    id              uuid primary key default gen_random_uuid(),
    client_id       uuid not null references public.clients (id) on delete cascade,
    kind            public.osint_fact_kind not null,
    text            text not null check (length(text) between 1 and 4000),
    source_kind     public.fact_source_kind not null,
    source_ref      jsonb not null default '{}'::jsonb,
    observed_at     timestamptz not null default now(),
    recorded_by     uuid not null,
    redacted_at     timestamptz,
    redacted_by     uuid,
    redacted_reason text,
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now(),
    constraint osint_facts_source_kind_valid
        check (source_kind in ('scraper','advisor'))
);

create index osint_facts_client_active_idx
    on public.osint_facts (client_id, observed_at desc)
    where redacted_at is null;
create index osint_facts_client_kind_idx
    on public.osint_facts (client_id, kind)
    where redacted_at is null;

-- ── 6. RLS — owner-only SELECT for the calling advisor ───────────────
alter table public.dossier_facts enable row level security;
alter table public.profile_facts enable row level security;
alter table public.osint_facts   enable row level security;

create policy "dossier_facts_owner_select" on public.dossier_facts
    for select to authenticated
    using (exists (
        select 1 from public.clients c
        where c.id = client_id and c.owner_id = auth.uid()
    ));

create policy "profile_facts_owner_select" on public.profile_facts
    for select to authenticated
    using (exists (
        select 1 from public.clients c
        where c.id = client_id and c.owner_id = auth.uid()
    ));

create policy "osint_facts_owner_select" on public.osint_facts
    for select to authenticated
    using (exists (
        select 1 from public.clients c
        where c.id = client_id and c.owner_id = auth.uid()
    ));

-- ── 7. Data migration: explode old JSONB columns into per-fact rows ──
-- 7a. passions: jsonb list of strings or {label, intensity, notes} dicts
insert into public.dossier_facts
    (client_id, kind, text, source_kind, source_ref, observed_at, recorded_by)
select
    d.client_id,
    'passion'::public.dossier_fact_kind,
    case when jsonb_typeof(p) = 'string' then p #>> '{}'
         else coalesce(p->>'label', p::text) end,
    'advisor'::public.fact_source_kind,
    jsonb_build_object('migrated_from','dossiers.passions','original',p),
    d.created_at,
    d.authored_by
from public.dossiers d, lateral jsonb_array_elements(d.passions) as p
where jsonb_typeof(d.passions) = 'array'
  and (case when jsonb_typeof(p) = 'string' then p #>> '{}'
            else coalesce(p->>'label', p::text) end) is not null
  and length(case when jsonb_typeof(p) = 'string' then p #>> '{}'
                  else coalesce(p->>'label', p::text) end) between 1 and 4000;

-- 7b. motivations: jsonb dict {fomo, status, bucket_list, notes} → one row per non-empty key
insert into public.dossier_facts
    (client_id, kind, text, source_kind, source_ref, observed_at, recorded_by)
select
    d.client_id,
    'motivation'::public.dossier_fact_kind,
    (k || ': ' || (case when jsonb_typeof(v) = 'string' then v #>> '{}' else v::text end)),
    'advisor'::public.fact_source_kind,
    jsonb_build_object('migrated_from','dossiers.motivations','key',k),
    d.created_at,
    d.authored_by
from public.dossiers d, lateral jsonb_each(d.motivations) as kv(k,v)
where jsonb_typeof(d.motivations) = 'object'
  and v is not null
  and (case when jsonb_typeof(v) = 'string' then v #>> '{}' else v::text end) <> ''
  and length(k || ': ' || (case when jsonb_typeof(v) = 'string' then v #>> '{}' else v::text end)) between 1 and 4000;

-- 7c. travel_history: jsonb list of {destination, year, note}
insert into public.dossier_facts
    (client_id, kind, text, source_kind, source_ref, observed_at, recorded_by)
select
    d.client_id,
    'travel_history'::public.dossier_fact_kind,
    trim(both ' · ' from concat_ws(' · ',
        nullif(coalesce(h->>'destination', h->>'place', h->>'where',''),''),
        nullif(coalesce(h->>'year',''),''),
        nullif(coalesce(h->>'note', h->>'summary',''),'')
    )),
    'advisor'::public.fact_source_kind,
    jsonb_build_object('migrated_from','dossiers.travel_history','original',h),
    d.created_at,
    d.authored_by
from public.dossiers d, lateral jsonb_array_elements(d.travel_history) as h
where jsonb_typeof(d.travel_history) = 'array'
  and jsonb_typeof(h) = 'object'
  and trim(both ' · ' from concat_ws(' · ',
        nullif(coalesce(h->>'destination', h->>'place', h->>'where',''),''),
        nullif(coalesce(h->>'year',''),''),
        nullif(coalesce(h->>'note', h->>'summary',''),'')
    )) <> '';

-- 7d. triggers / constraints / deal_breakers — flat string lists
insert into public.dossier_facts
    (client_id, kind, text, source_kind, source_ref, observed_at, recorded_by)
select
    d.client_id,
    'trigger'::public.dossier_fact_kind,
    case when jsonb_typeof(t) = 'string' then t #>> '{}' else t::text end,
    'advisor'::public.fact_source_kind,
    jsonb_build_object('migrated_from','dossiers.triggers'),
    d.created_at,
    d.authored_by
from public.dossiers d, lateral jsonb_array_elements(d.triggers) as t
where jsonb_typeof(d.triggers) = 'array'
  and length(case when jsonb_typeof(t) = 'string' then t #>> '{}' else t::text end) between 1 and 4000;

insert into public.dossier_facts
    (client_id, kind, text, source_kind, source_ref, observed_at, recorded_by)
select
    d.client_id,
    'constraint'::public.dossier_fact_kind,
    case when jsonb_typeof(c) = 'string' then c #>> '{}' else c::text end,
    'advisor'::public.fact_source_kind,
    jsonb_build_object('migrated_from','dossiers.constraints'),
    d.created_at,
    d.authored_by
from public.dossiers d, lateral jsonb_array_elements(d.constraints) as c
where jsonb_typeof(d.constraints) = 'array'
  and length(case when jsonb_typeof(c) = 'string' then c #>> '{}' else c::text end) between 1 and 4000;

insert into public.dossier_facts
    (client_id, kind, text, source_kind, source_ref, observed_at, recorded_by)
select
    d.client_id,
    'deal_breaker'::public.dossier_fact_kind,
    case when jsonb_typeof(b) = 'string' then b #>> '{}' else b::text end,
    'advisor'::public.fact_source_kind,
    jsonb_build_object('migrated_from','dossiers.deal_breakers'),
    d.created_at,
    d.authored_by
from public.dossiers d, lateral jsonb_array_elements(d.deal_breakers) as b
where jsonb_typeof(d.deal_breakers) = 'array'
  and length(case when jsonb_typeof(b) = 'string' then b #>> '{}' else b::text end) between 1 and 4000;

-- 7e. dream_trip_signals: jsonb dict → one row per non-empty key
insert into public.dossier_facts
    (client_id, kind, text, source_kind, source_ref, observed_at, recorded_by)
select
    d.client_id,
    'dream_signal'::public.dossier_fact_kind,
    (k || ': ' || (case when jsonb_typeof(v) = 'string' then v #>> '{}' else v::text end)),
    'advisor'::public.fact_source_kind,
    jsonb_build_object('migrated_from','dossiers.dream_trip_signals','key',k),
    d.created_at,
    d.authored_by
from public.dossiers d, lateral jsonb_each(d.dream_trip_signals) as kv(k,v)
where jsonb_typeof(d.dream_trip_signals) = 'object'
  and v is not null
  and (case when jsonb_typeof(v) = 'string' then v #>> '{}' else v::text end) <> ''
  and length(k || ': ' || (case when jsonb_typeof(v) = 'string' then v #>> '{}' else v::text end)) between 1 and 4000;

-- 7f. osint_notes: jsonb dict {linkedin, facebook, ..., other_key} → osint_facts
insert into public.osint_facts
    (client_id, kind, text, source_kind, source_ref, observed_at, recorded_by)
select
    d.client_id,
    case k when 'linkedin'  then 'linkedin'::public.osint_fact_kind
           when 'facebook'  then 'facebook'::public.osint_fact_kind
           when 'instagram' then 'instagram'::public.osint_fact_kind
           when 'press'     then 'press'::public.osint_fact_kind
           when 'company'   then 'company'::public.osint_fact_kind
           else 'other'::public.osint_fact_kind end,
    case when jsonb_typeof(v) = 'string' then v #>> '{}' else v::text end,
    'advisor'::public.fact_source_kind,
    jsonb_build_object('migrated_from','dossiers.osint_notes','key',k),
    d.created_at,
    d.authored_by
from public.dossiers d, lateral jsonb_each(d.osint_notes) as kv(k,v)
where jsonb_typeof(d.osint_notes) = 'object'
  and v is not null
  and (case when jsonb_typeof(v) = 'string' then v #>> '{}' else v::text end) <> ''
  and length(case when jsonb_typeof(v) = 'string' then v #>> '{}' else v::text end) between 1 and 4000;

-- ── 8. Drop the JSONB long-tail columns from dossiers ────────────────
-- Single source of truth is now the *_facts tables.
alter table public.dossiers
    drop column passions,
    drop column motivations,
    drop column travel_history,
    drop column triggers,
    drop column constraints,
    drop column deal_breakers,
    drop column dream_trip_signals,
    drop column osint_notes;
