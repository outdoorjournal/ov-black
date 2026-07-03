-- 0035_collection_notes.sql
-- Collection / wish list: allow a timeless, unattached note.
--
-- Before a trip has a timeline, travelers accumulate "maybes" — including
-- random notes that belong to no host card and have no scheduled time. The
-- Collection surface renders these. The 0014 XOR constraint
-- (`notes_anchored_or_attached`) required a note to have EXACTLY ONE of
-- {attached_to_node_id, starts_at}, which forbade a timeless collection note.
--
-- Relax XOR → "not both": a note may be attached (rides a host, no own time),
-- free-standing scheduled (its own starts_at), OR a Collection note (neither).
-- The only combination still rejected is attached AND self-scheduled, which
-- has no coherent meaning. Non-note rows remain unconstrained by this check.

alter table public.nodes
    drop constraint if exists notes_anchored_or_attached;

alter table public.nodes
    add constraint notes_anchored_or_attached check (
        type <> 'note'
        or not (attached_to_node_id is not null and starts_at is not null)
    );
