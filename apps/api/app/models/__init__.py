"""SQLAlchemy ORM models hand-aligned to the Supabase migration (D003).

Schema is owned by `supabase/migrations/0001_init.sql`. These classes are a
read/write surface only — never used to emit DDL. The shared Declarative
``Base`` lives here so every model inherits from one MetaData.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Project-wide declarative base. Bind nothing — engine lives in app.db."""


from app.models.invite import Invite  # noqa: E402,F401  (re-exported)
from app.models.profile import Profile, UserRole  # noqa: E402,F401  (re-exported)

__all__ = ["Base", "Invite", "Profile", "UserRole"]
