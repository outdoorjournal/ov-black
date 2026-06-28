-- 0028_booking_cancel_refund.sql
-- Resume hook (mvp-plan §234) — cancel + refund a booked/confirmed node.
--
-- An advisor cancels a booking: the covering payment is refunded (a settled
-- Braintree transaction) or voided (an unsettled one), a `reversal` invoice line
-- nets the charge to zero, and the node DEMOTES back to `approved` (no new
-- node_status — the cancellation lives on the bookings row + a node_history
-- `op="cancel"` row). A demoted node is re-bookable, so `bookings_one_per_node`
-- becomes PARTIAL (one live booking per node, ignoring cancelled rows).
--
-- These cancel/refund columns extend the committed booking record; the refund
-- Payment row (status='refunded') is recorded in the 0024 `payments` table and
-- linked back here via `refund_payment_id` (two-way cross-ref).
--
-- Redaction discipline (extends 0024): `refund_gateway_ref` and any processor
-- refund/void id are sensitive and must NEVER appear in a log record.
--
-- Conventions follow 0023/0024/0025: Postgres-native ENUM (D020, bound in
-- SQLAlchemy with create_type=False), additive + idempotent (safe to re-run /
-- `supabase db reset`).

-- ── 1. Enum: refund_status ───────────────────────────────────────────
-- 'failed' is reserved future-proofing — the service is fail-closed (a declined
-- refund rolls the whole cancel back), so today it writes only 'refunded' /
-- 'voided' / 'not_applicable'.
do $$
begin
    if not exists (
        select 1
          from pg_type t
          join pg_namespace n on n.oid = t.typnamespace
         where n.nspname = 'public'
           and t.typname = 'refund_status'
    ) then
        create type public.refund_status as enum (
            'refunded',
            'voided',
            'failed',
            'not_applicable'
        );
    end if;
end$$;

-- ── 2. bookings — cancel + refund columns (all nullable until cancelled) ──
alter table public.bookings
    add column if not exists cancelled_at        timestamptz,
    add column if not exists cancelled_by        uuid references auth.users (id) on delete set null,
    add column if not exists cancel_reason       text,
    add column if not exists refund_amount       numeric(12, 2),
    add column if not exists refund_currency     text,                   -- ISO 4217
    add column if not exists refund_status       public.refund_status,
    -- OUR cross-ref key for the refund (mirrors payments.gateway_reference).
    add column if not exists refund_gateway_ref  text,
    -- Two-way link to the refund Payment row (0024 payments, status='refunded').
    add column if not exists refund_payment_id   uuid references public.payments (id) on delete set null;

-- ── 3. One LIVE booking per node — now PARTIAL (cancelled rows excluded) ──
-- A cancelled booking demotes its node to `approved`, which is re-bookable; the
-- prior cancelled row stays for audit, so uniqueness must ignore it.
drop index if exists public.bookings_one_per_node;
create unique index if not exists bookings_one_per_node
    on public.bookings (node_id)
    where cancelled_at is null;
