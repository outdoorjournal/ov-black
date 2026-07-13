-- 0051_client_billing_address.sql
-- Structured billing-address parts on the client record (M005/I2, pay flow).
--
-- 0048 gave the client a single free-text `address`. The traveler pay page
-- (Braintree Hosted Fields) needs a structured billing address to pre-fill the
-- form and to feed Braintree's `transaction.sale({ billing: {...} })` — mirroring
-- the voyage-site checkout. Rather than parse the free-text line, we keep
-- `address` as the STREET line and add the remaining structured parts as their
-- own nullable columns:
--   * city         — locality (Braintree `locality`). NULL = unknown.
--   * region       — state / province / region (Braintree `region`). NULL = unknown.
--   * postal_code  — ZIP / postal code (Braintree `postal_code`). NULL = unknown.
--   * country_code — 2-letter ISO 3166-1 alpha-2 (Braintree `country_code_alpha2`,
--                    e.g. "US"). NULL = unknown.
--
-- All nullable — unknown until the advisor or the agent records them, and the
-- pay form lets the traveler complete/edit before charging. Additive + idempotent
-- (0032-0048 idiom): safe to re-run / db reset. A length CHECK pins the fixed-width
-- country code without an enum (country lists churn faster than a Postgres enum wants).

alter table public.clients
    add column if not exists city text,
    add column if not exists region text,
    add column if not exists postal_code text,
    add column if not exists country_code text;

alter table public.clients
    drop constraint if exists clients_country_code_iso3166,
    add constraint clients_country_code_iso3166
        check (country_code is null or country_code ~ '^[A-Z]{2}$');
