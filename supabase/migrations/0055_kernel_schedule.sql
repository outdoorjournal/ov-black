-- 0055_kernel_schedule.sql
-- Phase 2 of doc/itin-time.md: canonical wall-clock schedule columns.
--
-- The kernel time model (apps/api/app/kernel/schedule.py) stores what was
-- promised to a human — a wall time in an IANA zone, tied either to a trip day
-- (`relative`: day_offset from the itinerary's anchor_date) or to the world
-- (`pinned`: calendar dates; bookings and fixed-date events). The absolute
-- instant is DERIVED, never written: nodes.starts_at (tstzrange) stays for
-- range queries and becomes write-through output of the kernel in Phase 3.
--
-- Nothing reads these columns yet. This migration adds them, plus a backfill
-- function that converts existing rows from starts_at + metadata->
-- 'tz_offset_minutes', and runs it once. The function is kept (idempotent:
-- only touches schedule_kind IS NULL rows) so the Phase 3 cutover can re-run
-- it for rows written by the legacy path in between.
--
-- Backfill zone quality: the legacy representation stores a fixed offset, not
-- a zone, so converted rows get an `Etc/GMT±N` pseudo-zone — instant-exact
-- (the dual-read verification demands resolve(new) == starts_at) but DST-blind.
-- Real named zones arrive with Phase 3 writes; pseudo-zone rows are findable
-- via `start_tz like 'Etc/%'` for advisor review. Rows with a non-whole-hour
-- offset (none exist today) are skipped and left for manual review. Flights'
-- per-endpoint zones (depart vs arrive airport) are also a Phase 3 concern:
-- here both endpoints get the single legacy offset, which still reproduces the
-- stored instants exactly.
--
-- Idempotent idiom matching 0038/0039/0041 so `supabase db reset` re-runs are safe.

-- ── itineraries.anchor_date ──────────────────────────────────────────────────
-- The date Day 1 maps to; generalizes the days_anchor / date_start split
-- (doc/itin-time.md "One anchor per itinerary"). Retime = rewriting this one
-- field. days_anchor stays until Phase 6 (legacy reads still derive from it).

alter table public.itineraries
    add column if not exists anchor_date date;

update public.itineraries
   set anchor_date = coalesce(
        case when timing_kind = 'exact' then date_start end,
        days_anchor)
 where anchor_date is null;

-- ── nodes: canonical schedule columns ────────────────────────────────────────

alter table public.nodes
    add column if not exists schedule_kind text,
    add column if not exists start_day_offset integer,
    add column if not exists start_date date,
    add column if not exists start_wall_time time,
    add column if not exists start_tz text,
    add column if not exists end_day_offset integer,
    add column if not exists end_date date,
    add column if not exists end_wall_time time,
    add column if not exists end_tz text,
    add column if not exists needs_revalidation boolean not null default false;

-- Shape invariants, mirrored by app.kernel.adapter: unscheduled = all NULL;
-- relative carries day offsets and no dates; pinned carries dates and no
-- offsets; an end is either absent or complete in the schedule's own shape.
do $$ begin
    alter table public.nodes add constraint nodes_schedule_kind_valid
        check (schedule_kind in ('relative', 'pinned'));
exception when duplicate_object then null; end $$;

do $$ begin
    alter table public.nodes add constraint nodes_schedule_start_shape check (
        (schedule_kind is null
            and start_day_offset is null and start_date is null
            and start_wall_time is null and start_tz is null)
        or (schedule_kind = 'relative'
            and start_day_offset is not null and start_wall_time is not null
            and start_tz is not null and start_date is null)
        or (schedule_kind = 'pinned'
            and start_date is not null and start_wall_time is not null
            and start_tz is not null and start_day_offset is null)
    );
exception when duplicate_object then null; end $$;

do $$ begin
    alter table public.nodes add constraint nodes_schedule_end_shape check (
        (end_wall_time is null and end_tz is null
            and end_day_offset is null and end_date is null)
        or (schedule_kind = 'relative'
            and end_wall_time is not null and end_tz is not null
            and end_day_offset is not null and end_date is null)
        or (schedule_kind = 'pinned'
            and end_wall_time is not null and end_tz is not null
            and end_date is not null and end_day_offset is null)
    );
exception when duplicate_object then null; end $$;

-- ── backfill ─────────────────────────────────────────────────────────────────

create or replace function public.kernel_backfill_schedule()
returns table (converted integer, skipped integer)
language plpgsql
as $$
declare
    n record;
    n_converted integer := 0;
    n_skipped integer := 0;
    off_min integer;
    zone text;
    kind text;
    s_local timestamp;
    e_local timestamp;
begin
    for n in
        select nd.id, nd.starts_at, nd.status, nd.metadata,
               it.anchor_date as it_anchor
          from public.nodes nd
          join public.itineraries it on it.id = nd.itinerary_id
         where nd.starts_at is not null
           and nd.schedule_kind is null
    loop
        off_min := coalesce(nullif(n.metadata->>'tz_offset_minutes', '')::integer, 0);
        -- Etc/GMT pseudo-zones exist for whole hours in [-12h, +14h] only.
        -- Note the inverted POSIX sign: Etc/GMT-3 means UTC+3.
        if off_min % 60 <> 0 or off_min < -720 or off_min > 840 then
            n_skipped := n_skipped + 1;
            continue;
        end if;
        zone := case
            when off_min = 0 then 'Etc/GMT'
            when off_min > 0 then 'Etc/GMT-' || (off_min / 60)::text
            else 'Etc/GMT+' || (-off_min / 60)::text
        end;

        s_local := lower(n.starts_at) at time zone zone;
        e_local := case when upper(n.starts_at) is not null
                        then upper(n.starts_at) at time zone zone end;

        -- Committed nodes are world-pinned (booking pins — doc/itin-time.md
        -- "Pinnedness is a lifecycle property"). Anchorless itineraries have
        -- no Day 1 to be relative to, so their rows pin to their dates too.
        kind := case
            when n.status in ('booked', 'confirmed') then 'pinned'
            when n.it_anchor is null then 'pinned'
            else 'relative'
        end;

        if kind = 'relative' then
            update public.nodes set
                schedule_kind = 'relative',
                start_day_offset = (s_local::date - n.it_anchor),
                start_wall_time = s_local::time,
                start_tz = zone,
                end_day_offset = case when e_local is not null
                                      then (e_local::date - n.it_anchor) end,
                end_wall_time = e_local::time,
                end_tz = case when e_local is not null then zone end
            where id = n.id;
        else
            update public.nodes set
                schedule_kind = 'pinned',
                start_date = s_local::date,
                start_wall_time = s_local::time,
                start_tz = zone,
                end_date = e_local::date,
                end_wall_time = e_local::time,
                end_tz = case when e_local is not null then zone end
            where id = n.id;
        end if;
        n_converted := n_converted + 1;
    end loop;
    return query select n_converted, n_skipped;
end $$;

select * from public.kernel_backfill_schedule();
