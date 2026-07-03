-- 0032_itinerary_cover_image.sql
-- Feature image ("cover") for every itinerary — the voyage tile hero photo.
--
-- Basecamp lists a client's trips as tiles. Until now nothing on the itinerary
-- itself held an image, so the tiles were flat cream cards. We add a cached
-- cover to the row: a destination-derived photo (live Unsplash search, keyed on
-- the itinerary's primary destination) with a curated in-code default set as
-- the fallback. The cache lives here so hot reads never hit the rate-limited
-- Unsplash API — the backend only re-fetches when the derived subject changes
-- (see app/services/covers.py).
--
-- All columns are nullable: a legacy row with no stored cover resolves to a
-- deterministic default at read time, so no data backfill is required. A later
-- view/list opportunistically upgrades it to a real photo in the background.
--
-- Additive only. Idempotent idiom matches 0014–0022 so a repeated
-- `supabase db reset` is safe.

-- ── 1. Cover columns on public.itineraries ────────────────────────────
-- `cover_image_url` is the (Unsplash CDN or curated default) image URL.
-- `cover_image_alt` is the a11y/alt text (Unsplash `alt_description`, or null).
-- `cover_attribution` is `{name, profile_url}` crediting the Unsplash
-- photographer (Unsplash API ToS); null for curated defaults.
-- `cover_subject` is the normalized subject we last fetched for (e.g. "kyoto")
-- — the cache key that gates re-fetching.
-- `cover_source` is 'unsplash' | 'default', so we know the provenance (and can
-- retry a default → live photo once a destination is known).
alter table public.itineraries
    add column if not exists cover_image_url text;

alter table public.itineraries
    add column if not exists cover_image_alt text;

alter table public.itineraries
    add column if not exists cover_attribution jsonb;

alter table public.itineraries
    add column if not exists cover_subject text;

alter table public.itineraries
    add column if not exists cover_source text;
