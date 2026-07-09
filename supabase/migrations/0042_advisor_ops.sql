-- 0042_advisor_ops.sql
-- Wave F (mission control): the advisor Command Center gains a roster-wide
-- activity feed (GET /advisor/activity + the /advisor/feed SSE tick) and a
-- per-itinerary change replay (GET /itinerary/{id}/changes). Both read the
-- append-only history tables itinerary-first and time-ordered — but the only
-- indexes 0002 created lead with node_id/edge_id, so an itinerary-scoped read
-- has no usable path once history grows. Give each history table the
-- (itinerary_id, occurred_at desc, id desc) spine the keyset cursor walks.
--
-- invoices.issued_at: the moment an invoice went out is a first-class event on
-- the advisor feed ("invoice issued") and the honest `at` for the awareness
-- layer's invoice_unpaid signal. Until now issuing only flipped `status`, so
-- the closest timestamp was updated_at — overwritten by any later edit.
-- Stamped by issue_invoice() from here on; existing issued/paid invoices keep
-- NULL (pre-invariant data, same posture as D028's wipe rule).
--
-- Idempotent idiom matching 0038/0039 so re-runs under `supabase db reset` are safe.

create index if not exists node_history_itinerary_occurred_idx
    on public.node_history (itinerary_id, occurred_at desc, id desc);

create index if not exists edge_history_itinerary_occurred_idx
    on public.edge_history (itinerary_id, occurred_at desc, id desc);

alter table public.invoices
    add column if not exists issued_at timestamptz;
