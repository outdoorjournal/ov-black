-- 0016_node_cost.sql
-- M002 Phase B4 — first-class node cost (decision D-COST / mvp-plan §6).
--
-- Promotes a bookable node's price from the free-text `metadata` snapshot
-- string ("USD 1,234") to first-class, queryable columns so M005 invoicing
-- and the money gate can SUM(cost) per itinerary and reconcile it against
-- booked inventory. Per D-COST we store the NATIVE currency + amount on the
-- node (minimal multi-currency: one display currency is a read-side concern,
-- deferred); `cost_kind` records whether the amount is quoted per traveler or
-- as a single total so a later party-size pass can expand it correctly.
--
-- This is the static node cost. A flight's price is a REPRICEABLE quote held
-- only until it expires (D024) — that transient offer + its refresh history
-- live in the `node_offers` table (M005), not here. `cost_amount` is the
-- agreed cost at proposal time; the money gate re-prices before booking.
--
-- Additive only. All three columns are nullable: a non-bookable node
-- (free_time, note) or a not-yet-priced idea simply has no cost. Idempotent
-- idiom matches 0014/0015 so repeated `supabase db reset` is safe.

-- ── 1. New enum: cost_kind ────────────────────────────────────────────
-- Whether `cost_amount` is quoted per traveler (`per_person`) or as one total
-- for the node (`total`). Inventory providers that quote a whole-booking price
-- (Duffel offer total, Ratehawk stay total) map to `total`; OV-style
-- per-person experiences map to `per_person`. Postgres-native ENUM per D020
-- (SQLAlchemy binds it with create_type=False — the migration owns the type).
do $$
begin
    if not exists (
        select 1
          from pg_type t
          join pg_namespace n on n.oid = t.typnamespace
         where n.nspname = 'public'
           and t.typname = 'cost_kind'
    ) then
        create type public.cost_kind as enum ('per_person', 'total');
    end if;
end$$;

-- ── 2. New columns on public.nodes ────────────────────────────────────
-- numeric(12,2): money to two decimal places in native major units, matching
-- the `node_offers` / `bookings` draft schema in mvp-plan §8. `cost_currency`
-- is ISO 4217 (e.g. 'USD', 'EUR'). All nullable so existing rows stay valid.
alter table public.nodes
    add column if not exists cost_amount numeric(12, 2);

alter table public.nodes
    add column if not exists cost_currency text;

alter table public.nodes
    add column if not exists cost_kind public.cost_kind;

-- ── 3. Integrity: amount and currency travel together ─────────────────
-- Mirrors nodes_provenance_complete (source ⇔ source_id). A cost is only
-- meaningful with both halves: an amount with no currency can't be summed,
-- and a bare currency carries no value. `cost_kind` is independent (a node
-- may carry an amount before its per_person/total nature is known).
do $$
begin
    if not exists (
        select 1 from pg_constraint
         where conname = 'nodes_cost_amount_currency_together'
           and conrelid = 'public.nodes'::regclass
    ) then
        alter table public.nodes
            add constraint nodes_cost_amount_currency_together check (
                (cost_amount is null) = (cost_currency is null)
            );
    end if;
end$$;

-- ── 4. Index for the money gate's per-currency SUM ────────────────────
-- M005 sums cost per itinerary, grouped by currency. Partial — only priced
-- nodes participate, keeping the index small and the aggregate cheap.
create index if not exists nodes_cost_idx
    on public.nodes (itinerary_id, cost_currency)
    where cost_amount is not null;
