-- 0036_agent_session_list.sql
-- M006/PS2: un-collapse the single re-pinned agent session into a scoped,
-- resumable session LIST. Two additive columns + a scope-aware open-session
-- index.
--
-- Until now open_or_reuse_session kept exactly one live row per
-- (client_id, audience) and RE-PINNED its itinerary_id to whatever itinerary
-- you opened from (0009 anticipated parallel sessions but the reuse key never
-- took itinerary_id). So switching trips silently moved the same conversation.
-- PS2 makes reuse honour SCOPE: the most-recent LIVE session for the exact
-- (client_id, audience, itinerary_id), never re-pinned — opening trip A then
-- trip B yields two distinct sessions. A `title` (human or auto-derived from the
-- first user message) names each; `archived_at` soft-hides one from the list.
-- Additive + idempotent (0014-0017 idiom): safe to re-run / db reset.

-- ── 1. Columns: a human/auto title + soft-archive marker ──────────────
alter table public.agent_sessions
    add column if not exists title text;
alter table public.agent_sessions
    add column if not exists archived_at timestamptz;

-- ── 2. Scope-aware open-session index ─────────────────────────────────
-- The old lookup keyed on (client_id, audience) among open rows and re-pinned
-- on reuse. The new reuse selects the most-recent LIVE session (ended_at null
-- AND archived_at null) for the exact scope (client_id, audience, itinerary_id);
-- the list query filters the same live set by scope. `itinerary_id` is nullable
-- (NULL = basecamp scope) and Postgres indexes the NULLs, so basecamp sessions
-- are covered too. Replace the partial index to match the new key + ordering.
drop index if exists public.agent_sessions_client_audience_open_idx;
create index if not exists agent_sessions_scope_live_idx
    on public.agent_sessions (client_id, audience, itinerary_id, started_at desc)
    where ended_at is null and archived_at is null;
