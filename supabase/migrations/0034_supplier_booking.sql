-- 0034_supplier_booking.sql
-- Real supplier bookings (Bokun) — the `book_node` money gate now RESERVES +
-- CONFIRMS the reservation with the upstream supplier instead of leaving the
-- confirmation # for an advisor to enter by hand.
--
-- OV is merchant-of-record (D-BOOK): the traveler's payment clears (Braintree)
-- BEFORE booking, then the service reserves + confirms with the supplier at the
-- net rate — Bokun's RESERVE_FOR_EXTERNAL_PAYMENT two-step. The confirmation code
-- that comes back is stored in the EXISTING `supplier_ref` column (it always was
-- "the supplier confirmation #"); these columns add what a *programmatic* booking
-- also needs and a manual one never had:
--
--   supplier_source     — which provider actually holds the booking ('bokun'); the
--                         cancel path dispatches on it. NULL for a manual / no-
--                         supplier booking (unchanged behavior).
--   supplier_booking_id — the provider's INTERNAL booking id (Bokun `bookingId`),
--                         distinct from the human `bookingConfirmationCode`; the
--                         cancel call needs it.
--   supplier_selection  — the exact bookable slot we reserved (availability /
--                         start-time / rate / per-category participants), snapshotted
--                         for audit + idempotent re-tries. NOT sensitive.
--   supplier_raw        — the trimmed confirm response for audit. Providers must
--                         never put card data / secrets here (redaction discipline,
--                         mirrors 0024/0028).
--
-- Additive + idempotent (0014-0033 idiom): safe to re-run / `supabase db reset`.

alter table public.bookings
    add column if not exists supplier_source     text,
    add column if not exists supplier_booking_id text,
    add column if not exists supplier_selection  jsonb,
    add column if not exists supplier_raw        jsonb;
