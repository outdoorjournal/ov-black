-- 0047_itinerary_campaign_mood.sql
-- Two presentation/provenance fields on public.itineraries for the campaign
-- demo flow (inbound-campaign landing → pre-warmed intake → dashboard kickoff).
--
-- `campaign_id` is the slug of the marketing campaign a trip was started from
-- (e.g. 'olympus'), NULL for every ordinary trip. One nullable marker drives
-- three things: the dashboard's campaign-scoped auto-kickoff, the hero mood
-- preset, and the agent's campaign-awareness (surfaced in the traveler
-- context). It is provenance, not behaviour — no per-campaign branching hangs
-- off it beyond these seams.
--
-- `mood` is the curated atmospheric mood id (see apps/web/lib/atmos/moods.ts /
-- apps/agent/src/agent/moods.py) the dashboard hero renders. Until now mood was
-- only carried live over the set_mood SSE frame and lost on reload; persisting
-- it lets a seeded campaign show the right hero on first paint and makes a
-- chosen mood durable. NULL resolves to the default mood at read time.
--
-- Both nullable + additive, so no backfill; idempotent idiom matches 0032.

alter table public.itineraries
    add column if not exists campaign_id text;

alter table public.itineraries
    add column if not exists mood text;
