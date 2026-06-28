-- 0026_drop_invites.sql
-- Retire the invite-code flow. Sign-in is now purely email magic-link
-- (POST /auth/login). Advisors still "add a client" — that provisions the
-- client's auth row and emails a code-free welcome sign-in link via Supabase
-- inviteUserByEmail — but there is no OV-side invite code to redeem anymore,
-- so the table and its lifecycle (pending/consumed/cancelled/superseded) go
-- away. A client's "pending vs active" status is now derived from
-- clients.auth_user_id (backfilled on first login).
--
-- DROP ... CASCADE removes the table's indexes (incl. invites_active_by_owner_idx
-- from 0007) and RLS policies with it. The user_role enum is intentionally
-- left in place — public.profiles still uses it.
--
-- Data note: any unredeemed invites are abandoned by design. The affected
-- clients keep their clients row (auth_user_id still NULL → "pending") and can
-- be re-sent a welcome link from the Command Center.

drop table if exists public.invites cascade;
