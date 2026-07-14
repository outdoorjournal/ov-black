-- 0052_reading_catalog.sql
-- The reading catalog: a searchable corpus of editorial articles from the
-- concierge's owned media properties (Outside, Inc. — Outside, Backpacker,
-- Climbing, Trail Runner, Yoga Journal, …). The basecamp agent searches this
-- to suggest reading material; a chosen article is saved into the traveler's
-- Collection as an `article` node (0046), so this table is a *source* the
-- agent reads, never itinerary state itself.
--
-- Retrieval is Postgres full-text search: a `search_tsv` column (weighted
-- title > tags > excerpt) with a GIN index, queried with websearch_to_tsquery
-- + ts_rank. It's maintained by a BEFORE trigger rather than a GENERATED
-- column because `to_tsvector('english', …)` resolves the config through a
-- text→regconfig cast that Postgres treats as STABLE, not IMMUTABLE, so a
-- generated column (or bare expression index) is rejected. No pgvector yet —
-- an `embedding` column can be added later without touching this shape.
--
-- Not tied to a client or itinerary: this is shared editorial inventory,
-- read-only from the app's perspective (populated by seed / an ingestion job).

create table if not exists public.reading_catalog (
    id                   uuid primary key default gen_random_uuid(),
    -- Which owned property published it, e.g. 'Outside', 'Backpacker'.
    source_property      text not null,
    title                text not null,
    -- Canonical article URL. Unique so a re-seed / re-ingest upserts rather
    -- than duplicating the same piece.
    url                  text not null unique,
    -- OpenGraph hero image URL, shown on the suggestion flyout + Collection card.
    og_image             text,
    -- Short dek / OG description used for ranking and the flyout subline.
    excerpt              text,
    -- Free-form topical tags ('patagonia', 'trail-running', 'hut-trek') the
    -- agent matches against a traveler's destination + interests.
    tags                 text[] not null default '{}',
    reading_time_minutes integer,
    published_at         timestamptz,
    created_at           timestamptz not null default now(),
    -- Weighted search vector: title (A) > tags (B) > excerpt (C). Populated by
    -- the trigger below; never written by app code.
    search_tsv tsvector
);

-- Trigger-maintained tsvector (see header note on immutability). The function
-- body may use the STABLE text→regconfig form freely — only index/generated
-- expressions require IMMUTABLE.
create or replace function public.reading_catalog_tsv_update()
returns trigger
language plpgsql
as $$
begin
    new.search_tsv :=
        setweight(to_tsvector('english', coalesce(new.title, '')), 'A')
        || setweight(to_tsvector('english', array_to_string(new.tags, ' ')), 'B')
        || setweight(to_tsvector('english', coalesce(new.excerpt, '')), 'C');
    return new;
end;
$$;

create trigger reading_catalog_tsv_update_trg
    before insert or update on public.reading_catalog
    for each row execute function public.reading_catalog_tsv_update();

create index if not exists reading_catalog_search_tsv_idx
    on public.reading_catalog using gin (search_tsv);

-- RLS posture mirrors every other table (0010): enabled, zero policies — the
-- FastAPI service_role is the only reader; anon/authenticated are denied. The
-- corpus reaches the traveler only through the agent, never a direct client read.
alter table public.reading_catalog enable row level security;
