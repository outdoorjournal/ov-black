-- 0024_payments.sql
-- M005 Phase I2 — payments (decision D025 / D-PAY, mvp-plan §3).
--
-- A traveler pays an issued invoice; on a settled sale the invoice flips to
-- 'paid' and a payment row is recorded here. The table is GATEWAY-AGNOSTIC by
-- design (Braintree today, swappable later): it separates OUR cross-reference
-- key (gateway_reference, also written onto the processor-side transaction as
-- its order id) from the processor's own id (processor_transaction_id), keeps a
-- few portable normalized columns (instrument / last four / response code), and
-- a polymorphic `raw` jsonb holding the full processor payload so no state is
-- lost when a future gateway exposes different fields.
--
-- Redaction discipline: processor_transaction_id / last_four / raw are sensitive
-- and must NEVER appear in a log record (extends the existing sweep).
--
-- Conventions follow 0019/0020/0023: Postgres-native ENUM (D020, bound in
-- SQLAlchemy with create_type=False), relational + append-only (D005 — a row per
-- attempt). Additive + idempotent: safe to re-run / `supabase db reset`.

-- ── 1. Enum: payment_status ──────────────────────────────────────────
-- 'refunded' is future-proofing — I2 only writes succeeded / failed.
do $$
begin
    if not exists (
        select 1
          from pg_type t
          join pg_namespace n on n.oid = t.typnamespace
         where n.nspname = 'public'
           and t.typname = 'payment_status'
    ) then
        create type public.payment_status as enum (
            'succeeded',
            'failed',
            'refunded'
        );
    end if;
end$$;

-- ── 2. payments — one row per charge attempt ─────────────────────────
create table if not exists public.payments (
    id                       uuid primary key default gen_random_uuid(),
    invoice_id               uuid not null references public.invoices (id) on delete cascade,
    amount                   numeric(12, 2) not null,
    currency                 text not null,
    status                   public.payment_status not null,
    -- Gateway-agnostic identity.
    gateway                  text not null,            -- 'braintree' | 'fake' | 'stripe' | …
    gateway_reference        text not null,            -- OUR shared cross-ref key (= processor order id)
    processor_transaction_id text,                     -- the gateway's own id (e.g. Braintree id)
    -- Normalized-but-portable detail.
    instrument_type          text,                     -- 'credit_card' | 'paypal_account' | …
    last_four                text,
    processor_response       text,                     -- decline / response code text
    -- Polymorphic catch-all: the full processor payload (shape varies per gateway).
    raw                      jsonb not null default '{}'::jsonb,
    created_at               timestamptz not null default now()
);

create index if not exists payments_invoice_idx
    on public.payments (invoice_id);

-- Reverse lookup from a processor dashboard row back to our payment.
create index if not exists payments_processor_idx
    on public.payments (gateway, processor_transaction_id)
    where processor_transaction_id is not null;

-- ── 3. RLS — defense-in-depth (advisor OR linked traveler) ───────────
-- Mutations run through the API's owner-role connection (RLS bypassed); this
-- SELECT policy mirrors 0023 and flows invoice -> itinerary -> client.
alter table public.payments enable row level security;

drop policy if exists "payments_owner_select" on public.payments;
create policy "payments_owner_select" on public.payments
    for select to authenticated
    using (exists (
        select 1
          from public.invoices inv
          join public.itineraries it on it.id = inv.itinerary_id
          join public.clients c on c.id = it.client_id
         where inv.id = invoice_id
           and (c.owner_id = auth.uid() or c.auth_user_id = auth.uid())
    ));
