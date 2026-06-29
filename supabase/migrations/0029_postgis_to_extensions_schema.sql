-- 0029_postgis_to_extensions_schema.sql
-- Move the PostGIS extension out of `public` into the dedicated
-- `extensions` schema to satisfy the Supabase `extension_in_public`
-- linter (0014_extension_in_public).
--
-- PostGIS is NOT relocatable (`ALTER EXTENSION postgis SET SCHEMA` raises
-- "extension postgis does not support SET SCHEMA"), so the move is a
-- drop + recreate. That is safe here: the only objects depending on
-- postgis are the `nodes.location` / `nodes.route` geography columns and
-- their GIST indexes (added in 0014). They carry no data yet and are
-- deliberately absent from the ORM until geoalchemy2 lands
-- (see apps/api/app/models/itinerary.py), so dropping and re-adding them
-- is a no-op for application code.
--
-- `extensions` already exists on Supabase and is in extra_search_path
-- (supabase/config.toml), so unqualified geography references still
-- resolve; the re-added columns are schema-qualified to be explicit.
--
-- Idempotent and safe under `supabase db reset`: 0014 creates postgis in
-- `public` first, then this migration corrects it.

-- ── 1. Drop postgis. CASCADE also removes the dependent geography
--        columns + GIST indexes from 0014 (no data, not in the ORM). ────
drop extension if exists postgis cascade;

-- ── 2. Recreate it in the isolated extensions schema. ─────────────────
create schema if not exists extensions;
create extension if not exists postgis with schema extensions;

-- ── 3. Re-add the spatial columns CASCADE just dropped, resolving the
--        geography type from the extensions schema. ────────────────────
alter table public.nodes
    add column if not exists location extensions.geography(Point, 4326);
alter table public.nodes
    add column if not exists route extensions.geography(LineString, 4326);

-- ── 4. Re-create the GIST spatial indexes (0014 §7). ──────────────────
create index if not exists nodes_location_idx
    on public.nodes using gist (location)
    where location is not null;
create index if not exists nodes_route_idx
    on public.nodes using gist (route)
    where route is not null;
