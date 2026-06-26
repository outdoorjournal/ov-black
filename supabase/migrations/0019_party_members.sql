-- 0019_party_members.sql
-- M003/V1 — Party member model: a durable, household-scoped traveler identity.
--
-- Until now the only per-person row was public.travelers (0014), which hangs
-- off a party_id → itinerary_id. That makes a traveler PER-ITINERARY: the same
-- person on two trips is two unrelated rows with duplicated details. M003 needs
-- the opposite — "remember previous travelers" — so we split identity from
-- participation:
--
--   * party_members (NEW): the durable person, scoped to a client (the account
--     /household). Carries the identity-bearing fields (DOB, nationality,
--     dietary/medical/mobility, loyalty, emergency contact). Reused across every
--     itinerary that client takes.
--   * travelers (ALTERED): becomes the per-trip participation edge — a row now
--     just says "this member is on this itinerary's party" via party_member_id.
--
-- Collaboration is first-class: a member may be authored by the advisor, the
-- traveler (self-service), or the agent (recorded mid-conversation). The actor
-- is tracked on created_by_actor / updated_by_actor. Unlike Dossier/OSINT, party
-- data is shared knowledge the agent MAY reference and confirm.
--
-- Authorization is enforced in the API service layer (the API connects as the
-- owner role, bypassing RLS). The RLS policies below are defense-in-depth + for
-- any future direct supabase-js access, and mirror the established
-- itinerary→client→(advisor or traveler) ownership shape. Additive + idempotent
-- (0014-0018 idiom): safe to re-run.

-- ── 1. New enum: party_member_actor ──────────────────────────────────
-- Who authored / last touched a member — the collaboration provenance axis.
do $$
begin
    if not exists (
        select 1
          from pg_type t
          join pg_namespace n on n.oid = t.typnamespace
         where n.nspname = 'public'
           and t.typname = 'party_member_actor'
    ) then
        create type public.party_member_actor as enum ('advisor', 'traveler', 'agent');
    end if;
end$$;

-- ── 2. party_members — durable, client-scoped identity ───────────────
create table if not exists public.party_members (
    id                      uuid primary key default gen_random_uuid(),
    client_id               uuid not null references public.clients (id) on delete cascade,
    full_name               text not null check (length(full_name) between 1 and 200),
    date_of_birth           date,
    nationality             text,
    -- Free-text constraint fields (structured-enough for Fill to scan; richer
    -- structuring can come later without a migration via the jsonb columns).
    dietary                 text,
    medical                 text,
    mobility                text,
    loyalty_programs        jsonb not null default '[]'::jsonb,   -- [{program, number}]
    emergency_contact       jsonb not null default '{}'::jsonb,   -- {name, relationship, phone}
    relationship_to_primary text,                                  -- 'self','spouse','child',…
    is_primary              boolean not null default false,
    notes                   text,
    created_by_actor        public.party_member_actor not null,
    updated_by_actor        public.party_member_actor not null,
    recorded_by             uuid,            -- auth.uid() of advisor/traveler; null for agent
    archived_at             timestamptz,     -- soft-delete: keep history, hide from active list
    created_at              timestamptz not null default now(),
    updated_at              timestamptz not null default now()
);

-- Active household members for a client (the "remembered" reuse list).
create index if not exists party_members_client_active_idx
    on public.party_members (client_id)
    where archived_at is null;

-- At most one active primary (the account holder) per client.
create unique index if not exists party_members_one_primary_per_client
    on public.party_members (client_id)
    where is_primary and archived_at is null;

-- ── 3. travelers becomes the per-trip participation edge ─────────────
-- Link an itinerary-party traveler row to the durable member it represents.
-- on delete set null: archiving/removing a member never deletes trip history.
alter table public.travelers
    add column if not exists party_member_id uuid
        references public.party_members (id) on delete set null;

create index if not exists travelers_party_member_idx
    on public.travelers (party_member_id)
    where party_member_id is not null;

-- ── 4. RLS — defense-in-depth, collaborative (advisor OR linked traveler) ──
-- Mutations run through the API's owner-role connection (RLS bypassed); these
-- SELECT policies mirror the access model for any direct authenticated reads.
alter table public.party_members enable row level security;

drop policy if exists "party_members_collab_select" on public.party_members;
create policy "party_members_collab_select" on public.party_members
    for select to authenticated
    using (exists (
        select 1 from public.clients c
        where c.id = client_id
          and (c.owner_id = auth.uid() or c.auth_user_id = auth.uid())
    ));

-- 0014 enabled RLS on parties/travelers/node_parties but defined no policies,
-- leaving them readable only by service_role. Add the collaborative SELECT
-- policy now that there is a client to scope through.
drop policy if exists "parties_collab_select" on public.parties;
create policy "parties_collab_select" on public.parties
    for select to authenticated
    using (exists (
        select 1 from public.itineraries i
        join public.clients c on c.id = i.client_id
        where i.id = itinerary_id
          and (c.owner_id = auth.uid() or c.auth_user_id = auth.uid())
    ));

drop policy if exists "travelers_collab_select" on public.travelers;
create policy "travelers_collab_select" on public.travelers
    for select to authenticated
    using (exists (
        select 1 from public.parties p
        join public.itineraries i on i.id = p.itinerary_id
        join public.clients c on c.id = i.client_id
        where p.id = party_id
          and (c.owner_id = auth.uid() or c.auth_user_id = auth.uid())
    ));

drop policy if exists "node_parties_collab_select" on public.node_parties;
create policy "node_parties_collab_select" on public.node_parties
    for select to authenticated
    using (exists (
        select 1 from public.parties p
        join public.itineraries i on i.id = p.itinerary_id
        join public.clients c on c.id = i.client_id
        where p.id = party_id
          and (c.owner_id = auth.uid() or c.auth_user_id = auth.uid())
    ));
