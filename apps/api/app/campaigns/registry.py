"""Campaign definitions — the trim a campaign supplies to an ordinary trip.

Each :class:`Campaign` is keyed by a stable ``id`` (the slug that lands on the
itinerary's ``campaign_id`` column and in the landing-page URL). The seed
endpoint (``POST /demos/campaign/{id}``) reads a campaign to stamp the shell
itinerary's title / brief / mood; the dashboard kickoff reads
``spine_slugs_by_length`` to pick a length-variant spine; the agent reads
``reading_list`` when it fills the Collection with articles.

**Facts are NOT here.** A campaign's traveler (e.g. Robin Thurston) is a real
user provisioned ahead of the demo, so their dossier / profile / OSINT facts are
seeded by hand — not applied by the seed endpoint. Keeping facts out of the
registry avoids re-writing them on every landing and keeps the disclosure
discipline (what's referenceable vs. private) in the advisor's hands.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ArticleSeed:
    """One reading-list entry — a link to one of the campaign's editorial
    properties. The agent saves it to the Collection via the from-link path,
    which fetches the OpenGraph preview into an ``article`` card.
    """

    url: str
    publication: str


@dataclass(frozen=True)
class Campaign:
    """An inbound-campaign definition. All display trim, no behaviour."""

    id: str
    title: str
    brief: str
    #: Curated atmospheric mood id (apps/web/lib/atmos/moods.ts + agent moods.py).
    mood: str
    #: The assistant's first line on the pre-warmed intake surface (turn 0).
    opener: str
    #: A short private directive threaded into the agent's traveler context so it
    #: opens grounded in the campaign without a forked prompt. Never shown raw.
    directive: str
    #: Spine template lengths (nights) this campaign ships, ascending.
    supported_lengths: tuple[int, ...]
    #: nights → template slug, resolved by the kickoff after intake picks dates.
    spine_slugs_by_length: dict[int, str]
    #: Reading-list links the agent may drop into the Collection.
    reading_list: tuple[ArticleSeed, ...] = field(default_factory=tuple)


OLYMPUS = Campaign(
    id="olympus",
    title="Mount Olympus by First Light",
    brief=(
        "A guided ascent of the mythic mountain — Litochoro to the Mytikas "
        "summit, with the Aegean at your back."
    ),
    mood="olympus",
    opener=(
        "Mount Olympus has been waiting for you. I've started shaping the "
        "ascent — Litochoro, the refuge, the summit ridge. Before I build it "
        "out: who's coming with you, and roughly when are we going?"
    ),
    directive=(
        "This trip was started from the Mount Olympus inbound campaign. Open "
        "grounded in Olympus — the traveler already knows this is the "
        "destination, so don't ask where. Your job in intake is to narrow the "
        "WHEN (rough dates or a window) and the PARTY (who's coming), set the "
        "campaign mood, and record at most one genuine profile fact if it "
        "surfaces. Do not build the itinerary yet — that happens on the "
        "dashboard right after."
    ),
    supported_lengths=(5, 7, 14),
    spine_slugs_by_length={5: "olympus-5d", 7: "olympus-7d", 14: "olympus-14d"},
    reading_list=(
        ArticleSeed(
            url="https://www.outsideonline.com/adventure-travel/destinations/europe/mount-olympus-greece/",
            publication="Outside",
        ),
        ArticleSeed(
            url="https://www.climbing.com/places/climbing-mount-olympus-greece/",
            publication="Climbing",
        ),
        ArticleSeed(
            url="https://www.backpacker.com/trips/mount-olympus-greece-thru-hike/",
            publication="Backpacker",
        ),
    ),
)


CAMPAIGNS: dict[str, Campaign] = {OLYMPUS.id: OLYMPUS}


def get_campaign(campaign_id: str) -> Campaign | None:
    """Return the campaign for ``campaign_id``, or None if unknown."""
    return CAMPAIGNS.get(campaign_id)
