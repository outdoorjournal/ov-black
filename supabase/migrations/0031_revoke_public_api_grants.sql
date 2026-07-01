-- 0031_revoke_public_api_grants.sql
-- Remove the auto-generated REST/GraphQL API surface for every domain table.
--
-- Supabase grants table privileges on every `public` table to the `anon` and
-- `authenticated` roles by default. That makes each table DISCOVERABLE through
-- PostgREST/GraphQL with the public anon key — independent of RLS. RLS gates
-- the *rows*; the GRANT exposes the table's existence + shape. The Supabase
-- advisor flags this for every table ("anon role can SELECT … visible in the
-- GraphQL schema", + the signed-in `authenticated` equivalent, lint 0027).
--
-- This app's security model (R017; see the 0001_init.sql header) is that ALL
-- data access flows through FastAPI as the `postgres`/service role, which
-- bypasses both grants AND RLS. The ONLY direct PostgREST read in the web
-- client is `profiles.role` (apps/web/lib/role.ts), performed as the
-- authenticated user and gated by the `profiles_owner_select` policy
-- (auth.uid() = id). Therefore:
--   • `anon`          needs NOTHING in public, and
--   • `authenticated` needs SELECT on `public.profiles` ONLY.
-- Revoking everything else removes the whole domain from the public API; the
-- FastAPI perimeter (postgres role) is unaffected.
--
-- Idempotent: REVOKE of an absent privilege is a no-op; the re-GRANT is exact.

-- ── 1. Strip all table privileges from the two API roles (current tables) ──
revoke all privileges on all tables in schema public from anon, authenticated;

-- ── 2. Stop FUTURE tables from re-acquiring the default grant ─────────────
-- Supabase's default privileges re-grant to anon/authenticated on every newly
-- created table. Counter that for objects created by this migration role so a
-- later `create table public.…` doesn't silently re-open the API surface.
alter default privileges in schema public
    revoke all on tables from anon, authenticated;

-- ── 3. Re-grant the single read the web client actually performs ──────────
-- profiles.role lookup — authenticated only, own-row via profiles_owner_select.
grant select on table public.profiles to authenticated;
