-- 0025_bookings.sql
-- M005 Phase I3 — the money gate + booking workflow (decisions D024 / D-BOOK,
-- D025 / D-PAY; mvp-plan §6/§8).
--
-- A node's lifecycle stays on `node_status` (idea→proposed→approved→booked→
-- confirmed); booking + the repriceable-offer detail live in two structured
-- tables, NEVER in `metadata` (D024, mirrors D005):
--
--   node_offers — transient, time-boxed supplier quotes attached while a node is
--     pre-booking. A Duffel flight offer is a price HELD for a fixed window, not
--     a stable listing: it carries `amount` + `currency` + `priced_at` +
--     `expires_at`, the raw supplier payload, and a refresh-lineage self-FK so a
--     re-price (a fresh quote replacing a stale one) keeps history. Flights MUST
--     be re-priced before `approved → booked`; the money gate reconciles against
--     the re-priced/held amount and surfaces any delta.
--
--   bookings — the committed booking record: the amount actually charged, the
--     offer it was booked from (flights), the covering invoice LINE it was paid
--     by, `booked_by`/`booked_at`, the supplier confirmation # (PNR/order id) set
--     when it advances to `confirmed`, and the logged D-PAY `override_unpaid`
--     flag (an advisor booked against a merely *issued* line, not a *paid* one).
--     One live booking per node (a hard unique invariant).
--
-- The money gate itself (a node may go `approved → booked` only when a covering
-- PAID invoice line exists) is enforced in the service layer; the reconciliation
-- invariant (Σ paid invoice lines ⇔ Σ booked node costs) reads these tables plus
-- the 0023 ledger.
--
-- Conventions follow 0023/0024: relational + append-only (D005), FKs to nodes /
-- invoice_line_items / auth.users, and a defense-in-depth SELECT RLS policy (the
-- API writes through the owner-role connection, RLS bypassed). Additive +
-- idempotent (0014-0024 idiom): safe to re-run / `supabase db reset`.

-- ── 1. node_offers — time-boxed, repriceable supplier quotes ──────────
create table if not exists public.node_offers (
    id                       uuid primary key default gen_random_uuid(),
    node_id                  uuid not null references public.nodes (id) on delete cascade,
    -- Where the quote came from: 'duffel' (live re-price via the provider),
    -- 'snapshot' (frozen from the node's B4 cost when no live provider), or
    -- 'manual' (advisor-entered). Not an enum — providers are open-ended.
    source                   text not null,
    -- The provider's own offer id (a Duffel offer id), so a re-price can re-fetch
    -- it; null for snapshot/manual quotes.
    source_offer_id          text,
    amount                   numeric(12, 2) not null,
    currency                 text not null,            -- ISO 4217
    priced_at                timestamptz not null default now(),
    -- When the held price lapses; null = no expiry (snapshot/manual). The gate
    -- treats a flight offer as valid only while now() < expires_at.
    expires_at               timestamptz,
    -- Refresh lineage: the prior offer this quote re-prices (self-FK), so the
    -- re-price history is queryable. Null for the first quote on a node.
    refreshed_from_offer_id  uuid references public.node_offers (id) on delete set null,
    raw                      jsonb not null default '{}'::jsonb,  -- full supplier payload
    created_by               uuid references auth.users (id) on delete set null,
    created_at               timestamptz not null default now()
);

create index if not exists node_offers_node_idx
    on public.node_offers (node_id);

-- ── 2. bookings — the committed booking record (one live per node) ────
create table if not exists public.bookings (
    id                    uuid primary key default gen_random_uuid(),
    node_id               uuid not null references public.nodes (id) on delete cascade,
    -- The offer this was booked from (flights re-price before booking); null for
    -- nodes booked at their static B4 cost. Set null if the offer is later pruned.
    offer_id              uuid references public.node_offers (id) on delete set null,
    -- The invoice line that covers (pays for) this booking — the money-gate link.
    -- Set null if the line is somehow removed; the booking record itself stays.
    invoice_line_item_id  uuid references public.invoice_line_items (id) on delete set null,
    amount                numeric(12, 2) not null,   -- amount actually charged (re-priced/held)
    currency              text not null,             -- ISO 4217
    -- Supplier confirmation: PNR / order id, recorded when booked → confirmed.
    supplier_ref          text,
    change_cancel_terms   text,
    -- D-PAY override: booked against a merely *issued* (not *paid*) line. Logged
    -- here so the reconciliation surface + an audit can see it.
    override_unpaid       boolean not null default false,
    booked_by             uuid references auth.users (id) on delete set null,
    booked_at             timestamptz not null default now(),
    confirmed_at          timestamptz,
    created_at            timestamptz not null default now(),
    updated_at            timestamptz not null default now()
);

-- One LIVE booking per node (D024 "one-live-booking-per-node"). A cascade delete
-- with the node clears it; the MVP does not re-book a node in place.
create unique index if not exists bookings_one_per_node
    on public.bookings (node_id);

-- ── 3. RLS — defense-in-depth (advisor OR linked traveler) ───────────
-- Mutations run through the API's owner-role connection (RLS bypassed); these
-- SELECT policies mirror 0023's, walking node → itinerary → client.
alter table public.node_offers enable row level security;

drop policy if exists "node_offers_owner_select" on public.node_offers;
create policy "node_offers_owner_select" on public.node_offers
    for select to authenticated
    using (exists (
        select 1
          from public.nodes n
          join public.itineraries it on it.id = n.itinerary_id
          join public.clients c on c.id = it.client_id
         where n.id = node_id
           and (c.owner_id = auth.uid() or c.auth_user_id = auth.uid())
    ));

alter table public.bookings enable row level security;

drop policy if exists "bookings_owner_select" on public.bookings;
create policy "bookings_owner_select" on public.bookings
    for select to authenticated
    using (exists (
        select 1
          from public.nodes n
          join public.itineraries it on it.id = n.itinerary_id
          join public.clients c on c.id = it.client_id
         where n.id = node_id
           and (c.owner_id = auth.uid() or c.auth_user_id = auth.uid())
    ));
