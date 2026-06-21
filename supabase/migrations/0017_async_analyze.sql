-- 0017_async_analyze.sql
-- M002 Phase B5 — async itinerary Analyze (TravelGraph Phase 5).
--
-- An Analyze is an on-demand feasibility pass over an itinerary graph. It runs
-- in the background (FastAPI BackgroundTasks for the first cut), walks the
-- selected timeline, and records FINDINGS — structural problems (shallow) and
-- physical-feasibility problems like impossible drive-times between consecutive
-- nodes (standard). Fill (B6) and fork/reconcile (M004/G3) consume the latest
-- completed analysis instead of re-deriving feasibility themselves.
--
-- Two tables sit beside the existing graph (they NEVER mutate it — Analyze is
-- read-only over `nodes`/`edges`): `analyses` is one run with a status state
-- machine + the agent-readable aggregate `result`; `analysis_findings` is the
-- append-only list of individual problems, each Fill-shaped via `suggested_fix`.
--
-- Conventions: D003 (Supabase CLI owns raw-SQL DDL; SQLAlchemy is query-layer
-- only), D005 (relational + append-only, not JSONB blobs for the row spine),
-- D020 (Postgres-native ENUM for new enums). Idempotent idiom matches
-- 0014/0015/0016 (`do $$ begin ... end$$` for type creation, `if not exists`
-- everywhere) so repeated `supabase db reset` is safe.
--
-- NB: the Phase 5 handoff doc drafted this as `0016_async_analyze.sql`, but
-- 0016 was taken by node cost (B4); this is the same schema, renumbered.

-- ── 1. New enums ──────────────────────────────────────────────────────
-- analysis_status: the run state machine. queued -> running -> completed,
--   with failed/cancelled as terminal side-exits (see services/analyze.py).
-- analysis_depth: explicitly chosen by the caller, never inferred (D-ANALYZE).
--   `shallow` = structural only; `standard` = physical-feasibility envelope.
--   `deep` (live external data) is deferred for the MVP — the runner downgrades
--   a `deep` request to `standard` and records it, so the value stays valid.
-- finding_severity: info < suggest < warn < block. `block` = physical
--   impossibility; Fill must not propose candidates that don't resolve it.
do $$
begin
    if not exists (
        select 1 from pg_type t join pg_namespace n on n.oid = t.typnamespace
         where n.nspname = 'public' and t.typname = 'analysis_status'
    ) then
        create type public.analysis_status as enum (
            'queued', 'running', 'completed', 'failed', 'cancelled'
        );
    end if;

    if not exists (
        select 1 from pg_type t join pg_namespace n on n.oid = t.typnamespace
         where n.nspname = 'public' and t.typname = 'analysis_depth'
    ) then
        create type public.analysis_depth as enum ('shallow', 'standard', 'deep');
    end if;

    if not exists (
        select 1 from pg_type t join pg_namespace n on n.oid = t.typnamespace
         where n.nspname = 'public' and t.typname = 'finding_severity'
    ) then
        create type public.finding_severity as enum (
            'info', 'suggest', 'warn', 'block'
        );
    end if;
end$$;

-- ── 2. analyses — one run ─────────────────────────────────────────────
-- `scope` (jsonb) bounds the run: optional node_ids (null = whole itinerary),
-- time_window, party_id, and branches ('selected_only'|'all', default
-- selected_only). `inputs_hash` is sha256 of the canonicalized
-- {node ids, edge ids, scope, depth} at run start, so a re-request can find a
-- recent equivalent completed run (cache hit). `result` is the flat,
-- agent-readable aggregate (summary + stats + by_category + drive_times);
-- detailed problems live in analysis_findings. `external_calls` audits any
-- provider hops (standard/deep). `started_at`/`completed_at` mirror the
-- transitions for SLO tracking.
create table if not exists public.analyses (
    id              uuid primary key default gen_random_uuid(),
    itinerary_id    uuid not null references public.itineraries (id)
                                    on delete cascade,
    status          public.analysis_status not null default 'queued',
    depth           public.analysis_depth not null default 'standard',
    scope           jsonb not null default '{}'::jsonb,
    inputs_hash     text,
    requested_by    uuid,
    requested_kind  text not null default 'user',
    started_at      timestamptz,
    completed_at    timestamptz,
    result          jsonb,
    summary         text,
    external_calls  jsonb not null default '[]'::jsonb,
    error_detail    text,
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now()
);

-- ── 3. analysis_findings — append-only individual problems ────────────
-- `node_id` null = whole-itinerary finding; ON DELETE SET NULL so a finding
-- survives a later node purge (it's an audit record). `evidence` is structured
-- jsonb the agent reasons over; `suggested_fix` is Phase-6-FillProposal-shaped
-- (null when informational).
create table if not exists public.analysis_findings (
    id              uuid primary key default gen_random_uuid(),
    analysis_id     uuid not null references public.analyses (id)
                                    on delete cascade,
    node_id         uuid references public.nodes (id) on delete set null,
    severity        public.finding_severity not null,
    category        text not null,
    message         text not null,
    evidence        jsonb not null default '{}'::jsonb,
    suggested_fix   jsonb,
    created_at      timestamptz not null default now()
);

-- ── 4. Indexes ────────────────────────────────────────────────────────
-- list-by-itinerary; the in-flight-serialization check (one queued/running per
-- itinerary); the cache-hit lookup (completed run matching itinerary+hash+depth).
create index if not exists analyses_itinerary_idx
    on public.analyses (itinerary_id);
create index if not exists analyses_status_idx
    on public.analyses (status)
    where status in ('queued', 'running');
create index if not exists analyses_inputs_hash_idx
    on public.analyses (itinerary_id, inputs_hash, depth)
    where status = 'completed';
create index if not exists analysis_findings_analysis_idx
    on public.analysis_findings (analysis_id);
create index if not exists analysis_findings_node_idx
    on public.analysis_findings (node_id) where node_id is not null;
create index if not exists analysis_findings_severity_idx
    on public.analysis_findings (analysis_id, severity);

-- ── 5. RLS ────────────────────────────────────────────────────────────
-- Enabled to match 0014's parties/node_parties posture. The API's service-role
-- connection bypasses RLS; the JWT middleware + the draft-read gate in the
-- analyze router are the live authorization perimeter (R017). No policies yet.
alter table public.analyses          enable row level security;
alter table public.analysis_findings enable row level security;
