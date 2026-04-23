-- 0008_itineraries_client_fk.sql
-- Repoint itineraries.client_id to public.clients(id).
--
-- 0002 declared the FK against auth.users(id) because public.clients did not
-- exist yet (introduced in 0003). The app layer has always written a
-- clients.id into this column, so every INSERT into itineraries has been one
-- backfill-trigger away from a FK violation — surfaced in S04 once
-- _ensure_itinerary_for_client started firing on the first POST /sessions
-- for a client.
--
-- Idempotent via pg_constraint lookup so repeated `supabase db reset` is safe.

do $$
begin
    if exists (
        select 1 from pg_constraint
        where conname = 'itineraries_client_id_fkey'
          and conrelid = 'public.itineraries'::regclass
    ) then
        alter table public.itineraries
            drop constraint itineraries_client_id_fkey;
    end if;
end$$;

alter table public.itineraries
    add constraint itineraries_client_id_fkey
        foreign key (client_id)
        references public.clients (id)
        on delete set null;
