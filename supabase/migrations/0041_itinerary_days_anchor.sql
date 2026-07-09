-- 0041_itinerary_days_anchor.sql
-- Wave E (ADV-16): give "Day N" a stable identity. An unpinned trip (timing_kind
-- ≠ 'exact') is built in relative days — but the nodes underneath carry absolute
-- dates (nodes.starts_at), parked on whatever day the plan happened to be built.
-- `days_anchor` is the date Day 1 currently maps to, so Day N ≡ days_anchor +
-- (N−1) stays stable even when the earliest card is deleted (the previous
-- derivation — earliest scheduled node, else today — renumbered days).
--
-- Stamped by the API the first time anything is scheduled onto the timeline
-- (defaulting to the window's date_start, else the current UTC date). Retime
-- (ADV-17, the pinning gesture) shifts every scheduled node by
-- (new date_start − days_anchor) days and re-stamps the anchor; unpinning
-- (exact → window/flexible) keeps it, so cards stay put and Day-N labels hold.
--
-- Idempotent idiom matching 0038/0039 so re-runs under `supabase db reset` are safe.

alter table public.itineraries
    add column if not exists days_anchor date;
