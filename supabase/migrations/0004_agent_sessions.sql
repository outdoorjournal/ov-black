-- 0004_agent_sessions.sql
-- M001/S04: agent_sessions + agent_turns with day-one RLS (zero policies).
-- Mirrors the RLS-on-zero-policies posture from S02 (itineraries/nodes/edges)
-- and S03 (clients/dossiers): service_role is the only writer; anon and
-- authenticated are denied at the schema level. A scoped read policy will be
-- added in a later slice if/when the advisor surface needs direct DB reads.
-- Owned by Supabase CLI (D003) — SQLAlchemy reads/writes as a query layer only.

-- ── Enums ──────────────────────────────────────────────────────────────────
-- turn_role enumerates every kind of row that can land in agent_turns: user
-- prompts, assistant responses (post-stream, echoing what the client saw),
-- system messages, tool invocations/results, and error rows produced when a
-- turn exhausts retries.
create type public.turn_role as enum (
    'user', 'assistant', 'system', 'tool', 'error'
);

-- ── Tables ─────────────────────────────────────────────────────────────────

-- agent_sessions: one row per client conversation with the agent. The
-- surrogate UUID `id` is the primary key so REST paths can be stable; the
-- separate `agentcore_session_id` text column carries Bedrock AgentCore's
-- runtimeSessionId, which lets the service reuse runtime context across
-- requests without a migration if AgentCore ever changes the ID format.
-- UNIQUE(client_id, agentcore_session_id) guards against accidental
-- duplicate-session rows under concurrent session creation for the same
-- client.
create table public.agent_sessions (
    id                   uuid primary key default gen_random_uuid(),
    client_id            uuid not null references public.clients (id) on delete cascade,
    agentcore_session_id text not null,
    started_at           timestamptz not null default now(),
    ended_at             timestamptz,
    unique (client_id, agentcore_session_id)
);

-- agent_turns: append-only conversation log. UNIQUE(session_id, turn_index)
-- makes concurrent double-submits a DB-level error, not a race the service
-- has to win. `content` stores assistant text post-stream (what the client
-- actually saw) so Command Center replays match the user experience rather
-- than the raw upstream model output. `retried` counts silent retries per
-- turn (S04 slice verification reads this); `error_reason` carries a short
-- string tag (`upstream_unavailable`, `invalid_input`, …) on role='error'
-- rows. `first_token_ms` is null when retries exhaust before any token
-- streams, which is itself the signal of a failed turn.
create table public.agent_turns (
    id              uuid primary key default gen_random_uuid(),
    session_id      uuid not null references public.agent_sessions (id) on delete cascade,
    turn_index      int  not null,
    role            public.turn_role not null,
    content         text not null default '',
    model           text,
    latency_ms      int,
    first_token_ms  int,
    actor_kind      text not null,
    actor_id        text,
    retried         int  not null default 0,
    error_reason    text,
    created_at      timestamptz not null default now(),
    unique (session_id, turn_index)
);

-- ── Indexes ────────────────────────────────────────────────────────────────
-- Name is load-bearing: the conversation-replay query
--   select * from agent_turns where session_id = ? order by turn_index
-- uses the UNIQUE(session_id, turn_index) index; this secondary index backs
-- time-ordered reads (audit tooling) when turn_index ordering is not what we
-- want.

create index agent_turns_session_created_idx
    on public.agent_turns (session_id, created_at);

-- ── Row-Level Security ─────────────────────────────────────────────────────
-- Deliberately zero policies on both tables. Mirrors S02/S03: RLS enabled ⇒
-- anon/authenticated are denied; the FastAPI service_role bypasses RLS and
-- is the only writer. Cross-client turn leakage is defended at the service
-- layer (S04 T04/T05); this posture is the last line of defense if the
-- service ever forgets to scope.

alter table public.agent_sessions enable row level security;
alter table public.agent_turns    enable row level security;
