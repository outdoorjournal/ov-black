-- 0039_itinerary_proposed_status.sql
-- ADV-10: add a `proposed` value to public.itinerary_status so the itinerary
-- lifecycle is draft → proposed → approved. The advisor *proposes* the finished
-- plan to the traveler (draft → proposed, freezing the build for review); the
-- traveler then *approves* it — node-by-node or all-at-once — which derives the
-- itinerary to `approved`. This mirrors the node-level proposed → approved arc
-- (see public.node_status): the whole plan follows the same shape as its cards.
--
-- Also add proposed_by / proposed_at, siblings of approved_by / approved_at, so
-- the "presented on <date>, by <advisor>" audit is symmetric with approval.
--
-- Idempotent idiom (add value if not exists / add column if not exists) matching
-- 0005_node_status_discarded.sql + 0006_itinerary_approval.sql so re-runs under
-- `supabase db reset` are safe. Enum add-value is metadata-only (no table rewrite);
-- the new value is not *used* anywhere in this migration, so combining it with the
-- column adds in one file is safe (the "can't use a new enum value in the same
-- transaction" restriction only bites when you compare/insert it here).

-- Enum ─────────────────────────────────────────────────────────────────────
alter type public.itinerary_status add value if not exists 'proposed' before 'approved';

-- Columns ──────────────────────────────────────────────────────────────────
alter table public.itineraries
    add column if not exists proposed_by uuid
        references auth.users (id) on delete set null;

alter table public.itineraries
    add column if not exists proposed_at timestamptz;
