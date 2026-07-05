-- 0040_node_soft_delete.sql
-- Soft-delete for notes: a user may mark ANY of their notes as deleted,
-- removing them from view without destroying the row (and its history lineage).
--
-- Deletion of a note becomes a soft delete (stamp `deleted_at`) rather than a
-- hard `DELETE`, so the node_history "delete" op keeps its before-snapshot AND
-- the row itself survives for audit / potential undelete. Non-note nodes are
-- still hard-deleted by the service, so in practice only notes ever carry a
-- non-null `deleted_at` — which makes a blanket `deleted_at is null` read filter
-- safe across every node type.
--
-- Every graph read filters `deleted_at is null`, so a stamped note disappears
-- from the client mood board, advisor Command Center, and agent context alike.

alter table public.nodes
    add column if not exists deleted_at timestamptz;

comment on column public.nodes.deleted_at is
    'Soft-delete tombstone (notes only): non-null hides the node from every '
    'graph read while preserving the row + its node_history lineage.';

-- Active nodes for an itinerary (the read path). Partial so tombstoned notes
-- don't bloat the index that every graph fetch walks.
create index if not exists nodes_itinerary_active_idx
    on public.nodes (itinerary_id)
    where deleted_at is null;
