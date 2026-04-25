-- 0013_client_contacts.sql
-- Per-client contact methods: phone numbers, messenger handles, and social
-- handles. Replaces the implicit single-channel model (clients.email +
-- dossier.contact_preference) for everything past the invite — the invite
-- still flows to clients.email, but day-to-day contact info lives here.
--
-- A single typed kind enum covers phones, messengers, and social handles so
-- the advisor UX is one repeater without conditional schemas. Free-form
-- ``label`` lets the advisor distinguish "personal" vs "work" without
-- proliferating enum values. Same advisor-only RLS posture as the rest of
-- the per-client tables.

create type public.contact_kind as enum (
    'phone_cell', 'phone_home', 'phone_work',
    'whatsapp', 'signal', 'telegram', 'imessage',
    'instagram', 'linkedin', 'x', 'facebook', 'wechat',
    'other'
);

create table public.client_contacts (
    id          uuid primary key default gen_random_uuid(),
    client_id   uuid not null references public.clients (id) on delete cascade,
    kind        public.contact_kind not null,
    value       text not null check (length(value) between 1 and 256),
    label       text not null default '' check (length(label) <= 64),
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now()
);

create index client_contacts_client_idx
    on public.client_contacts (client_id, kind);

alter table public.client_contacts enable row level security;

create policy "client_contacts_owner_select" on public.client_contacts
    for select to authenticated
    using (exists (
        select 1 from public.clients c
        where c.id = client_id and c.owner_id = auth.uid()
    ));
