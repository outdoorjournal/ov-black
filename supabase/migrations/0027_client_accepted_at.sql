-- 0027_client_accepted_at.sql
-- Record when a client first signed in, so advisors can see if/when an invited
-- client accepted (vs. is still pending) and decide whether to nudge them.
--
-- Stamped the moment clients.auth_user_id is backfilled on first magic-link
-- login (see resolve_client_for_auth_user / _jit_backfill_client_auth_user_id).
-- NULL means "hasn't signed in yet" (access_status = pending). Legacy rows that
-- were already linked before this migration keep accepted_at NULL — they still
-- render as "active", just without a precise first-login timestamp.
--
-- Idempotent (add column if not exists) so repeated apply / db reset is safe.

alter table public.clients
    add column if not exists accepted_at timestamptz;
