-- 0043: collapse node statuses idea + proposed into a single default `pending`.
--
-- "Proposed to the traveler" is now derived from branch topology (a pending
-- node on a trunk is proposed; a pending node in a fork is an idea), so the
-- two pre-firmed statuses carry no distinct information. Postgres cannot
-- remove enum values in place, so this swaps in a new type.

create type public.node_status_new as enum
    ('pending', 'approved', 'booked', 'confirmed', 'discarded');

alter table public.nodes alter column status drop default;

alter table public.nodes
    alter column status type public.node_status_new
    using (case status::text
             when 'idea' then 'pending'
             when 'proposed' then 'pending'
             else status::text
           end)::public.node_status_new;

drop type public.node_status;
alter type public.node_status_new rename to node_status;

alter table public.nodes alter column status set default 'pending';
