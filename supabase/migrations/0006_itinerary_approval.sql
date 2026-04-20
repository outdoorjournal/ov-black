-- 0006_itinerary_approval.sql
-- M001/S08: add public.itinerary_status enum + status/approved_by/approved_at
-- columns on public.itineraries so the client-visibility gate is orthogonal
-- to the existing locked_by/locked_at advisory lock. Advisor can release the
-- lock mid-draft without flipping to approved, and re-lock for another edit.
-- Idempotent idiom (create ... if not exists / add column if not exists /
-- add value if not exists) matching 0005_node_status_discarded.sql so re-runs
-- are safe under `supabase db reset` or repeated migration application.

-- Enum ─────────────────────────────────────────────────────────────────────
do $$
begin
    if not exists (
        select 1
          from pg_type t
          join pg_namespace n on n.oid = t.typnamespace
         where n.nspname = 'public'
           and t.typname = 'itinerary_status'
    ) then
        create type public.itinerary_status as enum ('draft', 'approved');
    end if;
end$$;

-- Columns ──────────────────────────────────────────────────────────────────
alter table public.itineraries
    add column if not exists status public.itinerary_status
        not null default 'draft';

alter table public.itineraries
    add column if not exists approved_by uuid
        references auth.users (id) on delete set null;

alter table public.itineraries
    add column if not exists approved_at timestamptz;
