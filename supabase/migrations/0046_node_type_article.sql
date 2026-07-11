-- 0046_node_type_article.sql
-- Add the `article` node kind — a first-class reading-list card in the
-- Collection.
--
-- The Collection holds typed items; type determines rendering (card vs note)
-- and, derived from type, whether the item is schedulable. An `article` is a
-- first-class *card* (not a note), it lives in the Collection, and it is
-- NON-schedulable — a saved read (from the concierge's editorial properties or
-- a pasted link), never a thing that lands on the day timeline.
--
-- Additive, metadata-only, idempotent (`add value if not exists`) — matches the
-- idiom in 0005/0014 so a repeated `supabase db reset` is safe. The new value is
-- not used elsewhere in this migration (Postgres forbids using a freshly added
-- enum value in the same transaction); rows are written by application code.

alter type public.node_type add value if not exists 'article';
