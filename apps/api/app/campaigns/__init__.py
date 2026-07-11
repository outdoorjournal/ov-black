"""Marketing-campaign registry.

A *campaign* is the inbound-marketing entrypoint a trip can be started from: a
CTA in an article → a landing page with known params → a pre-warmed intake that
already knows the destination and shows bespoke imagery. It is **data + config,
not a forked code path** — everything still runs through the ordinary itinerary
graph + agent turn loop; the campaign only supplies the trim (title, mood,
opener, length-variant spine templates, a reading list).

See :mod:`app.campaigns.registry` for the ``Campaign`` model and the registry.
"""

from app.campaigns.registry import CAMPAIGNS, Campaign, get_campaign

__all__ = ["CAMPAIGNS", "Campaign", "get_campaign"]
