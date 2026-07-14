"""Campaign spine snapping — pick a length-variant spine for the chosen dates.

A campaign ships spine templates at a few fixed lengths (Olympus: 5 / 7 / 14
nights). Intake settles on real dates, which imply a night count that rarely
matches a shipped length exactly. Rather than author a spine per possible
length, we **snap** the requested nights to the nearest shipped length and hand
the agent a plain-language ``reason`` to explain the nudge to the traveler
("Olympus really wants at least five days on the mountain, so I've laid out a
five-day spine…").

Pure + deterministic so the kickoff is demo-reliable: the LLM narrates the
returned reason, it doesn't decide the number.
"""

from __future__ import annotations


def snap_length(requested_nights: int | None, supported: tuple[int, ...]) -> tuple[int, str]:
    """Snap ``requested_nights`` to the nearest ``supported`` spine length.

    Returns ``(snapped_length, reason)``. ``reason`` is a short human sentence
    when the snap changed the length (up or down), or ``""`` when it matched.
    ``supported`` must be non-empty; ties snap to the longer length (a trip is
    better a little roomier than a little rushed).
    """
    if not supported:
        raise ValueError("supported spine lengths must be non-empty")

    ordered = sorted(supported)
    if requested_nights is None:
        # No dates chosen yet — default to the LONGEST shipped spine so the trip
        # lands looking its fullest. It's easier to trim an over-generous ascent
        # once dates firm up than to coax the traveler into adding days.
        chosen = ordered[-1]
        return chosen, (
            f"I've laid out the full {chosen}-night ascent — the whole mountain, "
            f"unhurried. We can tighten it once your dates firm up."
        )

    # Nearest by absolute distance; ties favour the longer option.
    chosen = min(ordered, key=lambda n: (abs(n - requested_nights), -n))
    if chosen == requested_nights:
        return chosen, ""
    if chosen > requested_nights:
        return chosen, (
            f"You'd sketched about {requested_nights} nights — Olympus really "
            f"wants at least {chosen} to acclimatize, summit, and come down "
            f"unhurried, so I've laid it out over {chosen}."
        )
    return chosen, (
        f"You'd sketched about {requested_nights} nights — I've focused it into "
        f"a tighter {chosen}-night ascent so every day earns its place."
    )
