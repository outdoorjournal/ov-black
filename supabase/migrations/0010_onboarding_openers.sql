-- 0010_onboarding_openers.sql
-- M001/Basecamp: a curated bank of open-ended opening questions the
-- onboarding agent uses as its very first message on a brand-new client's
-- first /basecamp visit, plus a per-session record of which one was
-- chosen. The bank is intentionally small (curated copy, not user-
-- generated) and edited via SQL for v1; an editorial CMS surface comes
-- later if marketing needs rotation.
--
-- RLS posture mirrors every other table in this repo: enabled, zero
-- policies — the FastAPI service_role is the only reader/writer; anon
-- and authenticated are denied. This avoids standing up a one-off RLS
-- policy for a single read-only table.
--
-- Idempotent idiom (`if not exists` / `add column if not exists`) so
-- repeated `supabase db reset` is safe.

create table if not exists public.onboarding_openers (
    id           uuid primary key default gen_random_uuid(),
    prompt       text not null,
    weight       int  not null default 1,
    enabled      bool not null default true,
    created_at   timestamptz not null default now()
);

alter table public.onboarding_openers enable row level security;

-- The chosen opener is persisted on the agent_session row so that
-- reconnecting mid-conversation re-uses the same opening line, and so
-- the runtime can re-derive its "your first message must be …" directive
-- from session state alone. NULL means the session was opened outside
-- the basecamp flow (e.g. an existing /chat/{client_id} session).
alter table public.agent_sessions
    add column if not exists seeded_opener text;

insert into public.onboarding_openers (prompt) values
 ('What is one thing you have always wanted to do, but never had the chance?'),
 ('When you let yourself daydream about being away, where do you find yourself?'),
 ('What is a corner of the world that has been quietly tugging at you?'),
 ('When you travel, what are you trying to come home with?'),
 ('Tell me about the trip you almost took, but didn''t.'),
 ('What kind of stillness — or thrill — have you been missing lately?'),
 ('If a year of slow weekends abroad were given to you, where would they unfold?');
