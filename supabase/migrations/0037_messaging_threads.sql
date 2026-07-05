-- 0037_messaging_threads.sql
-- M006/PS7 — the unified human messaging substrate (Q13 = UNIFY).
--
-- PS2 un-collapsed the single re-pinned agent session into a scoped session
-- LIST, but that store is Artemis-only (agent_sessions/agent_turns). PS7 adds the
-- HUMAN channel the planner shell's "Advisor" people-circle summons: a durable
-- thread of human messages (traveler <-> advisor <-> that trip's party), with
-- NO agent turn. Per the PS0 spike (planner-shell.md §10, Q13) we UNIFY on one
-- thread/message store rather than bridge two — so PS8's @-mention is later just
-- a thread-scoped agent turn that inserts one `author_kind='artemis'` message,
-- and the disclosure sweep is a single assertion over messages.content on any
-- `audience='traveler'` thread regardless of who summoned.
--
-- Additive + back-compatible (0014-0036 idiom): PS2's agent_sessions/agent_turns
-- are untouched, so the Artemis session list keeps working. `agent_sessions`
-- gains a nullable `thread_id` as the forward hook — an AI-session thread will
-- bind exactly one agent_session (the engine) — but the backfill/replay of
-- existing sessions into `kind='ai_session'` threads is deliberately DEFERRED to
-- PS8 (the bridge slice), where messages become the shared spine. PS7 only needs
-- the human threads, which are independent of that backfill.
--
-- Authorization is enforced in the API service layer (the API connects as the
-- owner role, bypassing RLS) — see app/services/messaging.py. The RLS policies
-- below are defense-in-depth + for any future direct supabase-js access, and
-- follow the participant/client-ownership shape established in 0019. Idempotent:
-- safe to re-run / db reset.

-- ── 1. Enums ─────────────────────────────────────────────────────────
-- The thread container kind: an Artemis engine thread vs a human channel.
do $$
begin
    if not exists (
        select 1 from pg_type t join pg_namespace n on n.oid = t.typnamespace
        where n.nspname = 'public' and t.typname = 'thread_kind'
    ) then
        create type public.thread_kind as enum ('ai_session', 'human');
    end if;
end$$;

-- Who authored a message / who participates. 'artemis' is the explicit AI
-- attribution (PS8 rule 2); 'system' is for automated notices. Shared by
-- messages.author_kind and thread_participants.actor_kind. The disclosure
-- boundary itself is the thread's `audience` (reused session_audience enum),
-- NOT this column.
do $$
begin
    if not exists (
        select 1 from pg_type t join pg_namespace n on n.oid = t.typnamespace
        where n.nspname = 'public' and t.typname = 'thread_actor_kind'
    ) then
        create type public.thread_actor_kind as enum ('traveler', 'advisor', 'artemis', 'system');
    end if;
end$$;

-- ── 2. threads — the container ───────────────────────────────────────
-- `audience` (the disclosure boundary) lives on the thread, which is what makes
-- the PS8 invariant fall out. `itinerary_id` NULL = basecamp scope (you <->
-- advisor); non-null = that trip's thread (you <-> advisor <-> party).
create table if not exists public.threads (
    id           uuid primary key default gen_random_uuid(),
    client_id    uuid not null references public.clients (id) on delete cascade,
    itinerary_id uuid references public.itineraries (id) on delete cascade,
    kind         public.thread_kind not null,
    audience     public.session_audience not null default 'traveler',
    title        text,
    created_at   timestamptz not null default now(),
    archived_at  timestamptz
);

create index if not exists threads_scope_idx
    on public.threads (client_id, itinerary_id, kind, audience);

-- Exactly one live human thread per scope (get-or-create key). itinerary_id is
-- nullable and Postgres treats NULLs as distinct in a unique index, so two
-- partial indexes cover the itinerary vs basecamp cases separately.
create unique index if not exists threads_human_itinerary_uniq
    on public.threads (client_id, itinerary_id, audience)
    where kind = 'human' and itinerary_id is not null and archived_at is null;
create unique index if not exists threads_human_basecamp_uniq
    on public.threads (client_id, audience)
    where kind = 'human' and itinerary_id is null and archived_at is null;

-- ── 3. messages — the canonical human-visible transcript ─────────────
-- One store for both human turns and (PS8) Artemis turns. `author_id` is the
-- auth.users id for humans, NULL for artemis/system. `proposed_node_id` is the
-- PS8 hook for a card proposal flowing to the one graph (unused by human turns).
create table if not exists public.messages (
    id                uuid primary key default gen_random_uuid(),
    thread_id         uuid not null references public.threads (id) on delete cascade,
    author_kind       public.thread_actor_kind not null,
    author_id         uuid references auth.users (id) on delete set null,
    content           text not null check (length(content) between 1 and 8000),
    proposed_node_id  uuid references public.nodes (id) on delete set null,
    parent_message_id uuid references public.messages (id) on delete set null,
    created_at        timestamptz not null default now(),
    edited_at         timestamptz,
    removed_at        timestamptz
);

create index if not exists messages_thread_created_idx
    on public.messages (thread_id, created_at);

-- ── 4. thread_participants — explicit membership ─────────────────────
-- OV's disclosure rules must know exactly who can see a thread, so participation
-- is EXPLICIT (unlike voyage-site's implicit authorship/seen). A human thread
-- holds its human members (traveler + advisor today; party members join once
-- they have logins); Artemis is NOT a standing participant in a human thread —
-- it is summoned per-turn (PS8), so actor_id is NOT NULL and the PK is
-- (thread_id, actor_id).
create table if not exists public.thread_participants (
    thread_id    uuid not null references public.threads (id) on delete cascade,
    actor_kind   public.thread_actor_kind not null,
    actor_id     uuid not null references auth.users (id) on delete cascade,
    added_at     timestamptz not null default now(),
    last_read_at timestamptz,
    primary key (thread_id, actor_id)
);

create index if not exists thread_participants_actor_idx
    on public.thread_participants (actor_id);

-- ── 5. agent_sessions gains the forward hook ─────────────────────────
-- An AI-session thread binds exactly one agent_session (the engine). Nullable +
-- additive: PS2 sessions keep working with thread_id NULL until PS8 backfills.
alter table public.agent_sessions
    add column if not exists thread_id uuid
        references public.threads (id) on delete set null;

create index if not exists agent_sessions_thread_idx
    on public.agent_sessions (thread_id)
    where thread_id is not null;

-- ── 6. RLS — defense-in-depth (participant OR client ownership) ──────
-- Mutations run through the API's owner-role connection (RLS bypassed); these
-- SELECT policies mirror 0019: an authenticated user reads a thread iff they are
-- an explicit participant OR they own/are the thread's client (advisor owner or
-- the client's own auth link). A non-member (not a participant, not the
-- owner/client) matches nothing → sees nothing.
alter table public.threads enable row level security;
alter table public.messages enable row level security;
alter table public.thread_participants enable row level security;

drop policy if exists "threads_member_select" on public.threads;
create policy "threads_member_select" on public.threads
    for select to authenticated
    using (
        exists (
            select 1 from public.thread_participants tp
            where tp.thread_id = id and tp.actor_id = auth.uid()
        )
        or exists (
            select 1 from public.clients c
            where c.id = client_id
              and (c.owner_id = auth.uid() or c.auth_user_id = auth.uid())
        )
    );

drop policy if exists "messages_member_select" on public.messages;
create policy "messages_member_select" on public.messages
    for select to authenticated
    using (exists (
        select 1 from public.threads t
        where t.id = thread_id
          and (
            exists (
                select 1 from public.thread_participants tp
                where tp.thread_id = t.id and tp.actor_id = auth.uid()
            )
            or exists (
                select 1 from public.clients c
                where c.id = t.client_id
                  and (c.owner_id = auth.uid() or c.auth_user_id = auth.uid())
            )
          )
    ));

-- Terminal by design: a user sees only their OWN participant rows. The
-- `threads` policy above reads thread_participants to decide membership, so this
-- policy must NOT read `threads` back — that mutual reference is an infinite
-- recursion in Postgres RLS. Owner/advisor "who's in this thread" listing runs
-- through the API's owner-role connection (RLS bypassed), not this policy.
drop policy if exists "thread_participants_member_select" on public.thread_participants;
create policy "thread_participants_member_select" on public.thread_participants
    for select to authenticated
    using (actor_id = auth.uid());
