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
    #: Arrival airport IATA the kickoff flight search targets (origin = the
    #: traveler's home airport). None → the agent skips the flight step.
    arrival_airport: str | None = None
    #: Human place label for the airport ground-transfer ORIGIN (routing input).
    arrival_place: str | None = None
    #: Human place label for the transfer DESTINATION — the trip's first base.
    base_place: str | None = None


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
        "out, two things: how many days do you have for the mountain, and "
        "who's coming with you?"
    ),
    directive=(
        "This trip was started from the Mount Olympus inbound campaign. Open "
        "grounded in Olympus — the traveler already knows this is the "
        "destination, so don't ask where. Your ONLY job in intake is to settle "
        "two things, then hand off:\n"
        "1. LENGTH — how many days/nights they have for the mountain. This is "
        "the single most important thing to pin down: the ascent is built as a "
        "5-, 7-, or 14-night shape (short summit push, the classic ascent, or "
        "the unhurried full traverse), and the length decides which one you lay "
        "down on the dashboard next. Steer warmly toward a number of nights — if "
        "they're vague (\"about a week\"), that's fine, land on a rough count. "
        "The MOMENT you have it, call ``update_trip_timing``: ``window`` with "
        "``duration_nights`` (and a rough date range if they gave one), or "
        "``exact`` if they named firm dates. Do not finish intake without a "
        "duration recorded.\n"
        "2. PARTY — settle who is coming AND seat them on THIS trip; recording a "
        "companion in the household is not enough, they must be on the trip or "
        "the itinerary (flights, rooms, transfers, per-person costs) is sized "
        "wrong. First check ``party_members`` via ``get_traveler_context`` — a "
        "returning traveler already has family on file. For each person coming: "
        "someone ALREADY on file (a spouse, the kids) → ``add_trip_traveler`` "
        "with their member id; a brand-new person → ``record_party_member`` "
        "(which both saves and seats them). If someone on file is sitting this "
        "one out → ``remove_trip_traveler``. If it's genuinely just them, seat "
        "the primary via ``record_party_member`` (``is_primary=true``, their own "
        "name) so the ledger reads \"just you\". Don't leave known family "
        "unseated: if their kids are on file, confirm and seat them.\n"
        "Set the campaign mood, and record at most one genuine profile fact if "
        "it surfaces. Do NOT build the itinerary yet — the skeleton goes down on "
        "the dashboard right after. Once length and party are settled, call "
        "``complete_intake``."
    ),
    supported_lengths=(5, 7, 14),
    spine_slugs_by_length={5: "olympus-5d", 7: "olympus-7d", 14: "olympus-14d"},
    arrival_airport="SKG",
    arrival_place="Thessaloniki Airport (SKG), Greece",
    base_place="Litochoro, Greece",
    reading_list=(
        ArticleSeed(
            url="https://www.backpacker.com/trips/adventure-travel/mt-olympus-hiking-up-the-mountain-of-the-gods/",
            publication="Backpacker",
        ),
        ArticleSeed(
            url="https://www.climbing.com/places/this-way-to-paradise-andmdash-going-greek-on-the-island-of-kalymnos/",
            publication="Climbing",
        ),
        ArticleSeed(
            url="https://www.outsideonline.com/adventure-travel/destinations/europe/tiny-church-hidden-high-mountain-samos-greece/",
            publication="Outside",
        ),
    ),
)


CAMPAIGNS: dict[str, Campaign] = {OLYMPUS.id: OLYMPUS}


def get_campaign(campaign_id: str) -> Campaign | None:
    """Return the campaign for ``campaign_id``, or None if unknown."""
    return CAMPAIGNS.get(campaign_id)
