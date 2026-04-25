"""SQLAlchemy ORM models hand-aligned to the Supabase migration (D003).

Schema is owned by `supabase/migrations/0001_init.sql` +
`supabase/migrations/0002_itinerary_graph.sql`. These classes are a
read/write surface only — never used to emit DDL. The shared Declarative
``Base`` lives here so every model inherits from one MetaData.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Project-wide declarative base. Bind nothing — engine lives in app.db."""


from app.models.agent import (  # noqa: E402,F401  (re-exported)
    AgentSession,
    AgentTurn,
    TurnRole,
)
from app.models.client import (  # noqa: E402,F401  (re-exported)
    Client,
    ContactChannel,
    GroupType,
)
from app.models.invite import Invite  # noqa: E402,F401  (re-exported)
from app.models.onboarding import OnboardingOpener  # noqa: E402,F401  (re-exported)
from app.models.itinerary import (  # noqa: E402,F401  (re-exported)
    Edge,
    EdgeHistory,
    EdgeType,
    Itinerary,
    ItineraryStatus,
    Node,
    NodeHistory,
    NodeStatus,
    NodeType,
)
from app.models.profile import Profile, UserRole  # noqa: E402,F401  (re-exported)
from app.models.voodoo_doll import VoodooDoll  # noqa: E402,F401  (re-exported)

__all__ = [
    "AgentSession",
    "AgentTurn",
    "Base",
    "Client",
    "ContactChannel",
    "Edge",
    "EdgeHistory",
    "EdgeType",
    "GroupType",
    "Invite",
    "Itinerary",
    "ItineraryStatus",
    "Node",
    "NodeHistory",
    "NodeStatus",
    "NodeType",
    "OnboardingOpener",
    "Profile",
    "TurnRole",
    "UserRole",
    "VoodooDoll",
]
