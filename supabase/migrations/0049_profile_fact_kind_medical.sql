-- Add 'medical' to the profile_fact_kind enum so advisors and the agent
-- can record allergies, medical conditions, and other health context that
-- the traveler has self-expressed (Profile tier disclosure rules apply).
alter type public.profile_fact_kind add value if not exists 'medical';
