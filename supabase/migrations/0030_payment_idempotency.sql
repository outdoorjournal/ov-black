-- 0030_payment_idempotency.sql
-- M005 Phase I2/I3 hardening — make a charge safely retryable.
--
-- A client that retries POST /invoices/{id}/pay (network blip, double click)
-- must NOT double-charge. Two guards together close the window:
--   1. the service row-locks the invoice (SELECT ... FOR UPDATE) so concurrent
--      pays serialize — the loser sees status='paid' and is refused; and
--   2. an optional client-supplied Idempotency-Key, recorded here, so a retry
--      of the SAME logical attempt replays the prior outcome instead of issuing
--      a second charge.
--
-- Additive + idempotent: nullable column + PARTIAL unique index (only rows that
-- carry a key are constrained), so existing payments and key-less attempts are
-- unaffected. Safe to re-run / `supabase db reset`.

alter table public.payments
    add column if not exists idempotency_key text;

-- At most one payment row per (invoice, key). The partial predicate lets
-- key-less attempts (no idempotency header) coexist freely.
create unique index if not exists payments_idempotency_idx
    on public.payments (invoice_id, idempotency_key)
    where idempotency_key is not null;
