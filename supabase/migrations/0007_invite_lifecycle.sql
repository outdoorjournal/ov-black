-- 0007_invite_lifecycle.sql
-- Add cancel + re-issue lifecycle columns to public.invites. The historical
-- single-row-per-(email, advisor) shape becomes a log: every re-issue keeps
-- the old row and stamps it ``superseded_at``, every cancellation stamps
-- ``cancelled_at``. ``consumed_at`` retains its S01 atomicity role — the
-- redeem path now filters on all three being NULL to find an active invite.
--
-- Idempotent idiom (``add column if not exists``) so re-runs under
-- ``supabase db reset`` or repeated apply are safe.

alter table public.invites
    add column if not exists superseded_at timestamptz;

alter table public.invites
    add column if not exists cancelled_at timestamptz;

-- Redemption still probes by primary key, but the reissue/cancel paths look
-- up the latest active row per (email, role, created_by). A partial index
-- keeps that lookup cheap once an advisor has built up a history of sends.
create index if not exists invites_active_by_owner_idx
    on public.invites (created_by, email, role)
    where consumed_at is null
      and cancelled_at is null
      and superseded_at is null;
