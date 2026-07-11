-- 0048_client_profile_fields.sql
-- Traveler logistics fields on the client record (bugs.md: "Add Address /
-- Favorite Airport" + "USD vs EUR").
--
-- Three single-valued, operational attributes that belong to the traveler
-- rather than to any one trip, and are structured (not long-tail facts), so
-- they live as columns on `clients` rather than in the dossier/profile fact
-- stores:
--   * address           — free text; international addresses are irregular, so
--                         no structured parts. NULL = unknown.
--   * favorite_airport  — the traveler's home / preferred departure airport as
--                         a 3-letter IATA code (e.g. "JFK"). NULL = unknown.
--   * preferred_currency— ISO 4217 the traveler wants money shown in (e.g.
--                         "USD"). Drives read-time FX conversion of itinerary
--                         totals and the currency the agent quotes in. NULL =
--                         fall back to native provider currency.
--
-- Additive + idempotent (0032-0038 idiom): safe to re-run / db reset. Length
-- CHECKs pin the fixed-width codes without an enum (currencies + airports churn
-- faster than a Postgres enum wants to).

alter table public.clients
    add column if not exists address text,
    add column if not exists favorite_airport text,
    add column if not exists preferred_currency text;

alter table public.clients
    drop constraint if exists clients_favorite_airport_iata,
    add constraint clients_favorite_airport_iata
        check (favorite_airport is null or favorite_airport ~ '^[A-Z]{3}$');

alter table public.clients
    drop constraint if exists clients_preferred_currency_iso4217,
    add constraint clients_preferred_currency_iso4217
        check (preferred_currency is null or preferred_currency ~ '^[A-Z]{3}$');
