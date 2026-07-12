-- 0050_invoice_finance.sql
-- Finance workflow (doc/thoughts.md): human invoice numbers, a multi-currency
-- invoice that settles to ONE traveler currency, "viewed" tracking, and the
-- short-lived pay-time FX lock (payment_quotes).
--
-- Design (see the Finances plan): invoice LINE items stay in their node's NATIVE
-- currency and a single invoice may now hold several currencies (a EUR flight +
-- a GBP hotel). The money gate + reconciliation stay native and untouched —
-- coverage is Σ(native charge lines) gated on `invoices.status = 'paid'`, never on
-- the Payment currency. Two FX rates serve two purposes: a long-cached DISPLAY
-- rate (read-side, computed on the fly — nothing stored here) and a fresh, tightly
-- locked PAYMENT rate captured in `payment_quotes` for the actual charge.
--
-- Additive + idempotent (0023/0048 idiom): safe to re-run / `supabase db reset`.

-- ── 1. invoices — human number, settlement currency, viewed stamp ────────────
-- A per-project monotonic sequence gives each invoice a stable human number
-- (rendered as INV-000123). Existing rows are backfilled in created order.
create sequence if not exists public.invoices_number_seq;

alter table public.invoices
    add column if not exists number bigint,
    -- The single currency the traveler PAYS in (ISO 4217). NULL = pay native
    -- (legacy single-currency invoices, back-compat). Defaulted from the client's
    -- preferred_currency at create time.
    add column if not exists settlement_currency text,
    -- When the owning traveler first opened the issued invoice (advisor signal).
    add column if not exists first_viewed_at timestamptz;

-- Backfill numbers deterministically for any pre-existing invoices, then make the
-- sequence the column default so every new invoice draws one automatically.
do $$
declare
    r record;
begin
    for r in
        select id from public.invoices where number is null order by created_at, id
    loop
        update public.invoices set number = nextval('public.invoices_number_seq') where id = r.id;
    end loop;
end$$;

alter table public.invoices
    alter column number set default nextval('public.invoices_number_seq');

alter table public.invoices
    drop constraint if exists invoices_settlement_currency_iso4217,
    add constraint invoices_settlement_currency_iso4217
        check (settlement_currency is null or settlement_currency ~ '^[A-Z]{3}$');

-- ── 2. payment_quotes — the short-lived pay-time FX lock ─────────────────────
-- When a traveler opens the pay dialog we pull a FRESH rate per native currency,
-- compute the exact settlement charge, and lock it for a few minutes. The pay
-- call references the quote and charges the locked `settlement_amount`; an expired
-- or consumed quote forces a re-quote. `rates` records the native→settlement
-- multipliers used, for audit.
create table if not exists public.payment_quotes (
    id                  uuid primary key default gen_random_uuid(),
    invoice_id          uuid not null references public.invoices (id) on delete cascade,
    settlement_currency text not null,
    settlement_amount   numeric(12, 2) not null,
    rates               jsonb not null default '{}'::jsonb,
    created_at          timestamptz not null default now(),
    expires_at          timestamptz not null,
    consumed_at         timestamptz
);

create index if not exists payment_quotes_invoice_idx
    on public.payment_quotes (invoice_id);

-- ── 3. RLS — defense-in-depth (advisor OR linked traveler), mirrors 0023 ─────
-- Mutations run through the API's owner-role connection (RLS bypassed); this
-- SELECT policy mirrors invoices for any direct reads. Access flows invoice ->
-- itinerary -> client (owner or linked traveler).
alter table public.payment_quotes enable row level security;

drop policy if exists "payment_quotes_owner_select" on public.payment_quotes;
create policy "payment_quotes_owner_select" on public.payment_quotes
    for select to authenticated
    using (exists (
        select 1
          from public.invoices inv
          join public.itineraries it on it.id = inv.itinerary_id
          join public.clients c on c.id = it.client_id
         where inv.id = invoice_id
           and (c.owner_id = auth.uid() or c.auth_user_id = auth.uid())
    ));
