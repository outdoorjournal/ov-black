-- 0023_invoices.sql
-- M005 Phase I1 — invoices + line items (decision D025 / D-PAY, mvp-plan §3).
--
-- An itinerary becomes something a traveler pays for: an advisor assembles one
-- or more invoices (a deposit, a balance) over an itinerary's approved bookable
-- nodes. Each invoice is a small LEDGER — its line items are signed entries:
-- charges (usually node-priced via B4 cost), discounts and child/elderly
-- adjustments (negative), taxes/fees, and voids recorded as append-only
-- `reversal` lines that point back at the entry they cancel. The invoice total
-- is always Σ(line amounts) — there is NO denormalized total column, so the
-- line ledger is the single source of truth the M005 money gate (I3) reconciles
-- against (mvp-plan §5 "Money-gate correctness").
--
-- Per D-COST each line carries its native currency; for the MVP a line's
-- currency must equal its invoice's currency (enforced in the service layer) so
-- Σ is unambiguous (cross-currency display is a deferred read-side concern).
--
-- Conventions follow 0019/0020: Postgres-native ENUMs (D020, bound in
-- SQLAlchemy with create_type=False), relational + append-only (D005, voids are
-- reversal rows not deletes), and a defense-in-depth SELECT RLS policy (the API
-- writes through the owner-role connection, RLS bypassed). Additive +
-- idempotent (0014-0022 idiom): safe to re-run / `supabase db reset`.

-- ── 1. Enums: invoice_status + invoice_line_kind ─────────────────────
-- invoice lifecycle: draft (advisor assembling) -> issued (sent, payable) ->
-- paid (a covering payment settled, I2) ; void is the terminal cancel.
do $$
begin
    if not exists (
        select 1
          from pg_type t
          join pg_namespace n on n.oid = t.typnamespace
         where n.nspname = 'public'
           and t.typname = 'invoice_status'
    ) then
        create type public.invoice_status as enum (
            'draft',
            'issued',
            'paid',
            'void'
        );
    end if;
end$$;

-- What a (signed) line entry represents. `charge`/`tax`/`fee` are normally > 0;
-- `discount`/`adjustment`/`reversal` are normally < 0. `reversal` is the
-- journal-entry void: it negates the line in `reverses_line_item_id`.
do $$
begin
    if not exists (
        select 1
          from pg_type t
          join pg_namespace n on n.oid = t.typnamespace
         where n.nspname = 'public'
           and t.typname = 'invoice_line_kind'
    ) then
        create type public.invoice_line_kind as enum (
            'charge',
            'discount',
            'adjustment',
            'tax',
            'fee',
            'reversal'
        );
    end if;
end$$;

-- ── 2. invoices — one itinerary -> N invoices ────────────────────────
create table if not exists public.invoices (
    id            uuid primary key default gen_random_uuid(),
    itinerary_id  uuid not null references public.itineraries (id) on delete cascade,
    label         text not null default '',     -- e.g. "Deposit", "Balance"
    status        public.invoice_status not null default 'draft',
    currency      text not null,                -- ISO 4217; every line must match
    due_at        timestamptz,                  -- optional payment due date
    created_by    uuid references auth.users (id) on delete set null,
    created_at    timestamptz not null default now(),
    updated_at    timestamptz not null default now()
);

create index if not exists invoices_itinerary_idx
    on public.invoices (itinerary_id);

-- ── 3. invoice_line_items — the signed, append-only-after-issue ledger ─
-- A void appends a `reversal` row (amount = -original.amount,
-- reverses_line_item_id = original.id) rather than mutating/deleting — the
-- pair nets to zero and the audit trail is preserved (D005).
create table if not exists public.invoice_line_items (
    id                    uuid primary key default gen_random_uuid(),
    invoice_id            uuid not null references public.invoices (id) on delete cascade,
    -- The node this line bills for (null for a manual adjustment/tax/fee). On
    -- delete set null so removing a node never orphans an issued invoice's line.
    node_id               uuid references public.nodes (id) on delete set null,
    kind                  public.invoice_line_kind not null default 'charge',
    description           text not null default '',
    amount                numeric(12, 2) not null,   -- SIGNED (see enum comment)
    currency              text not null,             -- must equal invoices.currency
    -- For a `reversal` line: the line it voids. Self-FK; set null if the target
    -- somehow disappears (it shouldn't — lines are never hard-deleted post-issue).
    reverses_line_item_id uuid references public.invoice_line_items (id) on delete set null,
    created_by            uuid references auth.users (id) on delete set null,
    created_at            timestamptz not null default now(),
    updated_at            timestamptz not null default now()
);

create index if not exists invoice_line_items_invoice_idx
    on public.invoice_line_items (invoice_id);

-- At most one reversal per original line (the "already reversed" guard, also
-- enforced in the service; a partial unique index makes it a hard invariant).
create unique index if not exists invoice_line_items_one_reversal
    on public.invoice_line_items (reverses_line_item_id)
    where reverses_line_item_id is not null;

-- ── 4. RLS — defense-in-depth (advisor OR linked traveler) ───────────
-- Mutations run through the API's owner-role connection (RLS bypassed); these
-- SELECT policies mirror 0019/0020 for any direct reads. Access flows through
-- the owning itinerary -> client (owner or linked traveler).
alter table public.invoices enable row level security;

drop policy if exists "invoices_owner_select" on public.invoices;
create policy "invoices_owner_select" on public.invoices
    for select to authenticated
    using (exists (
        select 1
          from public.itineraries it
          join public.clients c on c.id = it.client_id
         where it.id = itinerary_id
           and (c.owner_id = auth.uid() or c.auth_user_id = auth.uid())
    ));

alter table public.invoice_line_items enable row level security;

drop policy if exists "invoice_line_items_owner_select" on public.invoice_line_items;
create policy "invoice_line_items_owner_select" on public.invoice_line_items
    for select to authenticated
    using (exists (
        select 1
          from public.invoices inv
          join public.itineraries it on it.id = inv.itinerary_id
          join public.clients c on c.id = it.client_id
         where inv.id = invoice_id
           and (c.owner_id = auth.uid() or c.auth_user_id = auth.uid())
    ));
