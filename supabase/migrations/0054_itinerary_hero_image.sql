-- 0054_itinerary_hero_image.sql
-- An explicit hero image on the itinerary (the tile + dashboard hero).
--
-- Until now the hero image was derived indirectly through `mood` (0047): the
-- frontend mapped an atmospheric mood id to a stock imageUrl. That indirection
-- was opaque and, for the itinerary dashboard, never actually wired up (the
-- adapter always fell back to the DEFAULT_MOOD image), so a trip's hero never
-- reflected the trip. An itinerary just has a hero image — make it a first-class
-- column that both the basecamp tile and the dashboard hero read directly.
--
-- `mood` stays: it still themes the concierge CHAT frame (keyword classifier).
-- It is simply no longer the source of the itinerary hero. Additive + idempotent
-- (0032-0053 idiom): safe to re-run / db reset.

alter table public.itineraries
    add column if not exists hero_image text;

-- Backfill the Mount Olympus campaign trips (and any forks of them) with the
-- campaign's summit hero so existing demo itineraries show the mountain without
-- a re-seed. Keyed off the persisted campaign/mood so it only touches Olympus.
update public.itineraries
   set hero_image = 'https://cdn-pub.prod.outdoorvoyage.com/operators/018f395d-288e-777c-a64d-3808a193b686/trips/018f39f5-7050-7b2c-a1c4-0c689797f113/images/xVMqslnvADKj.jpg'
 where hero_image is null
   and (campaign_id = 'olympus' or mood = 'olympus');
