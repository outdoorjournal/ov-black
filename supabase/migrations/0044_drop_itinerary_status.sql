-- 0044: delete the itinerary-level status lifecycle.
--
-- Visibility and handoff are now structural: an itinerary with
-- forked_from_id IS NULL is the official trunk (content reaches it only via
-- fork reconcile, i.e. "publish"); forks are private working copies. Display
-- buckets (in_studio / with_traveler / approved) are derived from node
-- statuses at read time, so the stored lifecycle and its audit columns go.

alter table public.itineraries
    drop column status,
    drop column proposed_by,
    drop column proposed_at,
    drop column approved_by,
    drop column approved_at;

drop type public.itinerary_status;
