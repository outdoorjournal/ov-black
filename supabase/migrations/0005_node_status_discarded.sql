-- 0005_node_status_discarded.sql
-- M001/S07: extend public.node_status with 'discarded' so mood-board cards
-- can round-trip pin / keep / discard transitions. Pin maps to 'approved',
-- keep stays 'proposed', discard maps to the new 'discarded' value.
-- Idempotent (`add value if not exists`) because auto-mode re-runs can
-- re-apply the migration. No table rewrites — enum add-value is metadata-only.

alter type public.node_status add value if not exists 'discarded';
