-- 0020_client_documents.sql
-- M003/V3 — Secure document vault: encrypted, expiry-tracked, reusable docs.
--
-- Travelers (and advisors on their behalf) store identity/booking documents —
-- passport, visa, insurance, vaccination — once, and reuse them across every
-- trip. The bytes live in S3 under SSE-KMS; only the metadata + the opaque
-- object key live here. The key is NEVER returned to a client or logged: reads
-- mint a short-TTL presigned URL on demand.
--
-- Like party_members (0019), documents are CLIENT-scoped (household assets), so
-- a passport uploaded for one itinerary is automatically available on the next.
-- A document MAY be optionally attributed to a specific party member
-- (party_member_id) — e.g. a child's passport — without changing ownership.
--
-- Authorization is enforced in the API service layer (the API connects as the
-- owner role, bypassing RLS). The RLS policy below is defense-in-depth and
-- mirrors the client→(advisor or traveler) ownership shape from 0019. Additive +
-- idempotent (0014-0019 idiom): safe to re-run.

-- ── 1. Enums: document_type + document_actor ─────────────────────────
do $$
begin
    if not exists (
        select 1
          from pg_type t
          join pg_namespace n on n.oid = t.typnamespace
         where n.nspname = 'public'
           and t.typname = 'document_type'
    ) then
        create type public.document_type as enum (
            'passport',
            'visa',
            'drivers_license',
            'national_id',
            'vaccination',
            'insurance',
            'loyalty_card',
            'other'
        );
    end if;
end$$;

-- Who uploaded / last touched a document — collaboration provenance, like 0019.
do $$
begin
    if not exists (
        select 1
          from pg_type t
          join pg_namespace n on n.oid = t.typnamespace
         where n.nspname = 'public'
           and t.typname = 'document_actor'
    ) then
        create type public.document_actor as enum ('advisor', 'traveler');
    end if;
end$$;

-- ── 2. client_documents — durable, client-scoped vault entries ───────
create table if not exists public.client_documents (
    id                uuid primary key default gen_random_uuid(),
    client_id         uuid not null references public.clients (id) on delete cascade,
    -- Optional attribution to a household member (e.g. a child's passport).
    -- on delete set null: removing a member never deletes the document.
    party_member_id   uuid references public.party_members (id) on delete set null,
    doc_type          public.document_type not null,
    label             text,                 -- human label, e.g. "Mum's passport"
    file_name         text not null,        -- original upload name (for download disposition)
    content_type      text not null,        -- MIME type, signed into the presigned PUT
    size_bytes        bigint,               -- set on upload confirmation
    -- The opaque S3 object key. NEVER returned to a client or written to a log;
    -- reads generate a presigned URL from it on demand.
    s3_key            text not null,
    expires_at        date,                 -- e.g. passport expiry; drives the "<6mo" warning
    notes             text,                 -- free text the traveler/advisor can add
    uploaded_at       timestamptz,          -- null until the browser confirms the S3 PUT
    created_by_actor  public.document_actor not null,
    recorded_by       uuid,                 -- auth.uid() of the advisor/traveler
    archived_at       timestamptz,          -- soft-delete: keep history, hide from active list
    created_at        timestamptz not null default now(),
    updated_at        timestamptz not null default now()
);

-- Active documents for a client (the reuse list).
create index if not exists client_documents_client_active_idx
    on public.client_documents (client_id)
    where archived_at is null;

-- Expiry sweep (passport-renewal warnings) over active docs that carry a date.
create index if not exists client_documents_expiry_idx
    on public.client_documents (expires_at)
    where archived_at is null and expires_at is not null;

-- Documents attributed to a specific member.
create index if not exists client_documents_party_member_idx
    on public.client_documents (party_member_id)
    where party_member_id is not null;

-- ── 3. RLS — defense-in-depth (advisor OR linked traveler) ───────────
-- Mutations run through the API's owner-role connection (RLS bypassed); this
-- SELECT policy mirrors 0019's collaborative access for any direct reads.
alter table public.client_documents enable row level security;

drop policy if exists "client_documents_collab_select" on public.client_documents;
create policy "client_documents_collab_select" on public.client_documents
    for select to authenticated
    using (exists (
        select 1 from public.clients c
        where c.id = client_id
          and (c.owner_id = auth.uid() or c.auth_user_id = auth.uid())
    ));
