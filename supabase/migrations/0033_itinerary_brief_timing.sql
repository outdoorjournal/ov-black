-- 0033: First-class trip brief + timing on itineraries.
--
-- An itinerary now carries the traveler's GOAL (a free-text brief like
-- "sailing in Greece with my family") and WHEN they want to go. Timing spans a
-- spectrum from exact dates through fuzzy-but-bounded ("generally summer, about
-- a week") to fully flexible, so we model it as a resolvable window + a target
-- duration + a discriminator, rather than a single rigid date range:
--
--   timing_kind = 'exact'    -> date_start/date_end ARE the fixed trip.
--   timing_kind = 'window'   -> date_start/date_end bound the acceptable
--                               window; duration_nights is the target length
--                               somewhere inside it ("~7 nights within Jun-Aug").
--   timing_kind = 'flexible' -> no dates yet; timing_note carries the intent.
--
-- timing_note is free-text that rides ALONGSIDE the structured fields to capture
-- what dates can't: the "why" and hard constraints -- "can't travel in August",
-- "must arrive back on a Sunday", "avoid school term". It is always allowed,
-- regardless of timing_kind.
--
-- Every column is nullable so existing rows and the lazy "Concierge draft"
-- auto-create path (services/agent.py) stay valid; the builder's first-run
-- intake fills them in.

create type public.itinerary_timing_kind as enum ('exact', 'window', 'flexible');

alter table public.itineraries
  add column brief           text,
  add column timing_kind     public.itinerary_timing_kind,
  add column date_start      date,
  add column date_end        date,
  add column duration_nights integer,
  add column timing_note     text;

-- Ordering + sanity guards. NULLs pass (partial info is the expected state
-- while the traveler is still deciding).
alter table public.itineraries
  add constraint itineraries_date_order_chk
    check (date_start is null or date_end is null or date_end >= date_start),
  add constraint itineraries_duration_positive_chk
    check (duration_nights is null or (duration_nights > 0 and duration_nights <= 365));

comment on column public.itineraries.brief is
  'Free-text trip goal, e.g. "sailing in Greece with my family". First-class intent, set at builder first-run.';
comment on column public.itineraries.timing_kind is
  'How to read the timing fields: exact (date_start/end are the trip) | window (date_start/end bound a window, duration_nights = target length) | flexible (no dates, see timing_note).';
comment on column public.itineraries.timing_note is
  'Free-text timing constraints + why, alongside the structured fields: "can''t go in August", "back by a Sunday", "summer, wife is a teacher".';
