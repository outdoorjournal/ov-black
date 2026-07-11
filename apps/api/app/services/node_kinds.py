"""Node-kind classification — is a card schedulable?

The Collection holds typed items. A node's ``type`` decides two things: how it
renders (a card vs a note), and — derived here, never stored — whether it can be
placed on the day timeline at all.

**Schedulable** items are the things that occupy time on a trip: destinations,
flights, hotels, experiences, meals, and the granular transit modes. Giving one
a ``starts_at`` is what moves it from the Collection onto a day.

**Non-schedulable** items live only in the Collection: an ``article`` (a saved
read / reading-list card) has no place on a day — it's a saved read, never a
timeline item. The write path enforces this: attempting to give an article a
``starts_at`` is a validation error.

``note`` is deliberately NOT in this set. Notes are dual-mode (0014): a
free-standing note can be time-anchored on the timeline, while a Collection note
is simply unscheduled. That existing behaviour stays untouched; notes are kept
out of the Collection *view* separately, not by making them non-schedulable.

Keeping the rule as one pure function (not a stored flag) means it can't drift
from the node's type, and the read model can expose ``schedulable`` for free.
"""

from __future__ import annotations

from app.models import NodeType

#: Types that can never carry a ``starts_at`` — Collection-only cards.
NON_SCHEDULABLE_TYPES: frozenset[NodeType] = frozenset({NodeType.article})


def is_schedulable(node_type: NodeType) -> bool:
    """Whether a node of this type may be placed on the timeline (given a time)."""
    return node_type not in NON_SCHEDULABLE_TYPES
