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
    SessionAudience,
    TurnRole,
)
from app.models.analysis import (  # noqa: E402,F401  (re-exported)
    Analysis,
    AnalysisDepth,
    AnalysisFinding,
    AnalysisStatus,
    FindingSeverity,
)
from app.models.booking import Booking, NodeOffer  # noqa: E402,F401  (re-exported)
from app.models.client import Client, ContactChannel  # noqa: E402,F401
from app.models.client_contact import (  # noqa: E402,F401  (re-exported)
    ClientContact,
    ContactKind,
)
from app.models.document import (  # noqa: E402,F401  (re-exported)
    ClientDocument,
    DocumentActor,
    DocumentType,
)
from app.models.dossier import Dossier  # noqa: E402,F401  (re-exported)
from app.models.dossier_fact import (  # noqa: E402,F401  (re-exported)
    DossierFact,
    DossierFactKind,
    FactSourceKind,
)
from app.models.invoice import (  # noqa: E402,F401  (re-exported)
    Invoice,
    InvoiceLineItem,
    InvoiceLineKind,
    InvoiceStatus,
    Payment,
    PaymentStatus,
)
from app.models.itinerary import (  # noqa: E402,F401  (re-exported)
    CostKind,
    Edge,
    EdgeHistory,
    EdgeType,
    ForkStatus,
    Itinerary,
    ItineraryStatus,
    Node,
    NodeHistory,
    NodeRole,
    NodeStatus,
    NodeType,
)
from app.models.onboarding import OnboardingOpener  # noqa: E402,F401  (re-exported)
from app.models.osint_fact import (  # noqa: E402,F401  (re-exported)
    OsintFact,
    OsintFactKind,
)
from app.models.party import (  # noqa: E402,F401  (re-exported)
    NodeParty,
    Party,
    PartyMember,
    PartyMemberActor,
    Traveler,
)
from app.models.profile import Profile, UserRole  # noqa: E402,F401  (re-exported)
from app.models.profile_fact import (  # noqa: E402,F401  (re-exported)
    ProfileFact,
    ProfileFactKind,
)
from app.models.template import (  # noqa: E402,F401
    CardTemplate,
    TemplateEdge,
    TemplateNode,
)

__all__ = [
    "AgentSession",
    "SessionAudience",
    "AgentTurn",
    "Analysis",
    "AnalysisDepth",
    "AnalysisFinding",
    "AnalysisStatus",
    "Base",
    "Booking",
    "CardTemplate",
    "Client",
    "ClientContact",
    "ClientDocument",
    "ContactChannel",
    "ContactKind",
    "CostKind",
    "DocumentActor",
    "DocumentType",
    "Dossier",
    "DossierFact",
    "DossierFactKind",
    "Edge",
    "EdgeHistory",
    "EdgeType",
    "FactSourceKind",
    "FindingSeverity",
    "ForkStatus",
    "Invoice",
    "InvoiceLineItem",
    "InvoiceLineKind",
    "InvoiceStatus",
    "Itinerary",
    "ItineraryStatus",
    "Node",
    "NodeHistory",
    "NodeOffer",
    "NodeParty",
    "NodeRole",
    "NodeStatus",
    "NodeType",
    "OnboardingOpener",
    "OsintFact",
    "OsintFactKind",
    "Party",
    "PartyMember",
    "PartyMemberActor",
    "Payment",
    "PaymentStatus",
    "Profile",
    "ProfileFact",
    "ProfileFactKind",
    "TemplateEdge",
    "TemplateNode",
    "Traveler",
    "TurnRole",
    "UserRole",
]
