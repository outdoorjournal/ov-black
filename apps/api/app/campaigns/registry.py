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
    properties. The dashboard kickoff seeds these onto the traveler's itinerary
    as ``article`` reading-list nodes (deterministically, alongside the spine),
    and the concierge's opener drops a tappable chip per read into its greeting.

    ``title`` is load-bearing — it's the chip label and the flyout headline — so
    it's required. The rest enriches the flyout (hero image, dek, reading time)
    when we have it; missing pieces degrade gracefully to a placeholder.
    """

    url: str
    publication: str
    title: str
    og_image: str | None = None
    excerpt: str | None = None
    reading_time_minutes: int | None = None


@dataclass(frozen=True)
class Campaign:
    """An inbound-campaign definition. All display trim, no behaviour."""

    id: str
    title: str
    brief: str
    #: Curated atmospheric mood id (apps/web/lib/atmos/moods.ts + agent moods.py).
    #: Themes the concierge chat frame — NOT the itinerary hero (see hero_image).
    mood: str
    #: The trip's hero image URL — stamped onto the itinerary at seed time and
    #: rendered directly by the basecamp tile + the dashboard hero.
    hero_image: str
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
    #: Variant of ``directive`` for a trip whose length is already settled
    #: (an explicit duration or pinned dates on the itinerary) — it must tell
    #: the agent NOT to ask how long the trip is. None → ``directive`` is used
    #: regardless of timing state.
    directive_length_settled: str | None = None

    def directive_for(self, *, length_settled: bool) -> str:
        """The private directive to thread into this turn's prompt.

        The directive leads the system prompt every turn, so a stale intake
        goal ("pin down the length") outshouts the trip brief's settled
        timing — the swap here is what actually stops the agent re-asking
        "how many days do you have?" after the length is on file.
        """
        if length_settled and self.directive_length_settled:
            return self.directive_length_settled
        return self.directive


def _olympus_directive(*, length_settled: bool) -> str:
    """Assemble the Olympus private directive.

    The campaign ships ONE shape — the full 14-night traverse — so neither
    variant ever asks how long the traveler has or offers length options.
    The intake variant records the fixed 14 nights at the close (plus any
    dates the traveler volunteers); the settled variant — picked the moment
    the itinerary carries a length, whether intake recorded one or the
    kickoff persisted the 14-night default — additionally forbids touching
    timing at all unless the traveler reopens it.
    """
    intro = (
        "This trip was started from the Mount Olympus inbound campaign. Open "
        "grounded in Olympus — the traveler already knows this is the "
        "destination, so don't ask where. "
    )
    if length_settled:
        length_part = (
            "The trip's LENGTH is ALREADY SETTLED — it is on file in the trip "
            "brief and the mountain shape is laid down. NEVER ask how many "
            "days or nights they have, in any phrasing — not as an opener, "
            "not as a confirmation, not at the close. Reopen timing ONLY if "
            "the traveler themselves asks to change it, and record the change "
            "via ``update_trip_timing``. Your one remaining intake job is the "
            "PARTY, then hand off:\n"
        )
        party_number = ""
        close_gate = "Once the party is settled, call ``complete_intake``."
    else:
        length_part = (
            "The trip's LENGTH is FIXED: the ascent is built as the full 14-night "
            "traverse — every ridge, every refuge, nothing rushed. That is the "
            "ONLY shape this campaign ships. NEVER ask how many days or nights "
            "they have, and NEVER present length options (no 5- or 7-night "
            "variants exist). Speak of the trip as the 14-night traverse when it "
            "comes up naturally. If the traveler volunteers firm dates or a date "
            "range, record them via ``update_trip_timing`` (``exact`` for firm "
            "dates, else ``window`` with ``duration_nights=14``); if they name a "
            "different length anyway, record what they actually said — the "
            "dashboard still lays down the 14-night ascent and narrates why. "
            "Otherwise record 14 via ``update_trip_timing`` (``window``, "
            "``duration_nights=14``) at the close, or just move on — the "
            "dashboard lays down the 14-night spine by default. Your one intake "
            "job is the PARTY, then hand off:\n"
        )
        party_number = ""
        close_gate = "Once the party is settled, call ``complete_intake``."
    return (
        intro
        + length_part
        + party_number
        + "PARTY — settle who is coming AND seat them on THIS trip; recording a "
        "companion in the household is not enough, they must be on the trip or "
        "the itinerary (flights, rooms, transfers, per-person costs) is sized "
        "wrong. First check ``party_members`` via ``get_traveler_context`` — a "
        "returning traveler already has family on file. For each person coming: "
        "someone ALREADY on file (a spouse, the kids) → ``add_trip_traveler`` "
        "with their member id; a brand-new person → ``record_party_member`` "
        "(which both saves and seats them). If someone on file is sitting this "
        "one out → ``remove_trip_traveler``. If it's genuinely just them, seat "
        "the primary via ``record_party_member`` (``is_primary=true``, their own "
        'name) so the ledger reads "just you". Don\'t leave known family '
        "unseated: if their kids are on file, confirm and seat them. But a "
        'MAYBE is not a yes: a companion floated with hedging ("might join", '
        '"don\'t hold me to it") is NOT seated, NOT recorded, and NOT '
        "cross-examined against the household file — acknowledge lightly, move "
        "on, and never re-raise it, especially not at the close. Settling the "
        "party means capturing what the traveler actually committed to, even "
        'when that is "just me, for now".\n'
        "Set the campaign mood. And when the traveler volunteers something real "
        "about themselves — a decades-old dream of this summit, a passion, a "
        "fear — record ONE profile fact for it (``record_profile_fact``) that "
        "same turn; the campaign's goals never crowd out a genuinely "
        "offered piece of who they are. Do NOT build the itinerary yet — the "
        "skeleton goes down on the dashboard right after. " + close_gate
    )


OLYMPUS = Campaign(
    id="olympus",
    title="Mount Olympus by First Light",
    brief=(
        "A guided ascent of the mythic mountain — Litochoro to the Mytikas "
        "summit, with the Aegean at your back."
    ),
    mood="olympus",
    # The Mytikas summit — from the cornerstone OV trip ("Path to Symbolism").
    hero_image=(
        "https://cdn-pub.prod.outdoorvoyage.com/operators/"
        "018f395d-288e-777c-a64d-3808a193b686/trips/"
        "018f39f5-7050-7b2c-a1c4-0c689797f113/images/xVMqslnvADKj.jpg"
    ),
    opener=(
        "Mount Olympus has been waiting for you. I've started shaping the "
        "full fourteen-night traverse — Litochoro, the refuges, the summit "
        "ridge, nothing rushed. Before I build it out, one thing: who's "
        "coming with you?"
    ),
    directive=_olympus_directive(length_settled=False),
    directive_length_settled=_olympus_directive(length_settled=True),
    supported_lengths=(14,),
    spine_slugs_by_length={14: "olympus-14d"},
    arrival_airport="SKG",
    arrival_place="Thessaloniki Airport (SKG), Greece",
    base_place="Litochoro, Greece",
    reading_list=(
        ArticleSeed(
            url="https://www.backpacker.com/trips/adventure-travel/mt-olympus-hiking-up-the-mountain-of-the-gods/",
            publication="Backpacker",
            title="Mt. Olympus: Hiking Up the Mountain of the Gods",
            excerpt=(
                "A trail-by-trail guide to the classic Litochoro-to-Mytikas "
                "ascent — the refuges, the ridgeline, and what the throne of "
                "Zeus asks of your legs."
            ),
            reading_time_minutes=9,
            og_image="https://cdn.backpacker.com/wp-content/uploads/2022/04/Spring22BP_Dispatch_Olympus2_bjk.jpg",
        ),
        ArticleSeed(
            url="https://www.climbing.com/places/this-way-to-paradise-andmdash-going-greek-on-the-island-of-kalymnos/",
            publication="Climbing",
            title="This Way to Paradise: Going Greek on the Island of Kalymnos",
            excerpt=(
                "Why the little Aegean island became one of the world's great "
                "sport-climbing pilgrimages — sea-cliff tufas, taverna nights, "
                "and endless limestone."
            ),
            reading_time_minutes=7,
            og_image="https://cdn.climbing.com/wp-content/uploads/2012/06/going-greek-on-the-island-of-kalymnos.jpg",
        ),
        ArticleSeed(
            url="https://www.outsideonline.com/adventure-travel/destinations/europe/tiny-church-hidden-high-mountain-samos-greece/",
            publication="Outside",
            title="The Tiny Church Hidden High in the Mountains of Samos, Greece",
            excerpt=(
                "A pilgrimage on foot to a chapel wedged into a Greek "
                "mountainside — the kind of quiet detour that turns a hike into "
                "a story."
            ),
            reading_time_minutes=6,
            og_image="https://cdn.outsideonline.com/wp-content/uploads/migrated-images_parent/migrated-images_51/samos_fe.jpg",
        ),
    ),
)


CAMPAIGNS: dict[str, Campaign] = {OLYMPUS.id: OLYMPUS}


def get_campaign(campaign_id: str) -> Campaign | None:
    """Return the campaign for ``campaign_id``, or None if unknown."""
    return CAMPAIGNS.get(campaign_id)
