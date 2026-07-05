-- 0038_client_invited_at.sql
-- ADV-1 / G-INVITE-LATER — silent client create.
--
-- Until now every `POST /clients` was atomic: create the client + Dossier AND
-- mint the Supabase auth row + email a welcome sign-in link. There was no way
-- for an advisor to stand up a client and quietly build for them before ever
-- notifying them. `access_status` was derived from `auth_user_id` alone
-- (NULL = "pending", set = "active"), which cannot distinguish a client who was
-- INVITED and hasn't accepted from one who was NEVER invited.
--
-- `invited_at` is that missing signal: the moment the welcome link was first
-- issued (NULL = never invited). The three-state `access_status` now falls out:
--   * auth_user_id IS NOT NULL            -> "active"    (signed in)
--   * invited_at   IS NOT NULL            -> "pending"   (invited, awaiting login)
--   * else                                -> "uninvited" (silently created)
--
-- Additive + idempotent (0032-0037 idiom): safe to re-run / db reset. Every
-- existing row predates invite-later and was created via the atomic
-- welcome-email path, so backfill `invited_at = created_at` — they were all
-- invited at creation.

alter table public.clients
    add column if not exists invited_at timestamptz;

update public.clients
    set invited_at = created_at
    where invited_at is null;
