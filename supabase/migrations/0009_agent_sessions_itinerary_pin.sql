-- 0009_agent_sessions_itinerary_pin.sql
-- M001/S11: agent_sessions gain an optional itinerary pin so a single client
-- can run parallel sessions against different itineraries (planning one trip
-- while asking Q&A about another). NULL means the session is unpinned —
-- onboarding (no itineraries yet) or general Q&A (agent queries across all
-- the client's itineraries). Non-NULL means planning-scoped to that draft.
--
-- This migration also prepares for removing the implicit one-itinerary-
-- per-client constraint enforced at the service layer; no DB-level constraint
-- change is needed since 0002 never declared uniqueness.
--
-- Idempotent idiom matches 0005/0006 so repeated `supabase db reset` is safe.

alter table public.agent_sessions
    add column if not exists itinerary_id uuid
        references public.itineraries (id) on delete set null;

create index if not exists agent_sessions_itinerary_id_idx
    on public.agent_sessions (itinerary_id);
