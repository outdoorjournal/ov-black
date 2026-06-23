-- 0018_agent_session_audience.sql
-- Advisor-private agent sessions, separate from the traveler-facing thread.
--
-- Until now POST /sessions was idempotent per client_id — a single shared
-- conversation. An advisor chatting from the itinerary view therefore posted
-- into the SAME thread the traveler sees. This adds an `audience` axis so a
-- client can carry two independent open sessions:
--   - 'traveler' (default): the client-facing conversation — the traveler, and
--     any advisor who deliberately joins it. Unchanged behaviour; existing
--     rows backfill to 'traveler'.
--   - 'advisor': a private advisor<->AI workspace the traveler never sees.
-- Reuse is keyed per (client_id, audience); the service gates a traveler actor
-- to the 'traveler' audience only (advisors may open either). Postgres-native
-- ENUM per D020 — SQLAlchemy binds it with create_type=False (the migration
-- owns the type). Additive + idempotent (0014-0017 idiom): safe to re-run.

-- ── 1. New enum: session_audience ────────────────────────────────────
do $$
begin
    if not exists (
        select 1
          from pg_type t
          join pg_namespace n on n.oid = t.typnamespace
         where n.nspname = 'public'
           and t.typname = 'session_audience'
    ) then
        create type public.session_audience as enum ('traveler', 'advisor');
    end if;
end$$;

-- ── 2. New column on public.agent_sessions ───────────────────────────
-- NOT NULL with a default so existing rows backfill to 'traveler' (every
-- session opened before this migration was the client-facing thread).
alter table public.agent_sessions
    add column if not exists audience public.session_audience not null default 'traveler';

-- ── 3. Index for the open-session-by-audience reuse lookup ────────────
-- open_or_reuse_session selects the live row for a (client_id, audience):
--   where client_id = ? and audience = ? and ended_at is null
-- Partial on the open rows keeps it small (ended sessions are never reused).
create index if not exists agent_sessions_client_audience_open_idx
    on public.agent_sessions (client_id, audience)
    where ended_at is null;
