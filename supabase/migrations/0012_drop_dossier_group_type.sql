-- 0012_drop_dossier_group_type.sql
-- Drop the dossier.group_type column. The dossier captures notes about the
-- *person* (passions, motivations, contact channel, net worth); the makeup
-- of any specific trip belongs on an itinerary, not on this row. The
-- public.group_type enum becomes unreferenced after the drop, so we drop
-- it too — re-creating it later is one ALTER TYPE away if needed.

alter table public.dossiers drop column group_type;
drop type public.group_type;
