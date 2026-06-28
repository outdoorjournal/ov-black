"""Party member CRUD + per-trip attach (M003/V1).

A party member is the durable, household-scoped traveler identity (0019). It is
authored collaboratively by three actors — advisor, traveler (self-service), and
agent (mid-conversation) — so every write pins the ``actor`` server-side; the
request body never carries it (mirroring fact ``source_kind``).

Authorization is enforced by the *router* (it resolves the caller's identity and
the client it may touch) before calling in here; these functions take an already
-authorized ``client_id``. The two resolution helpers below mirror the existing
advisor (`_load_client_owned_by`) and traveler (`resolve_client_for_auth_user`)
scoping so a router can collapse to a 404 the D015 way.

DELETE is a soft archive (``archived_at`` stamp): a removed member stays linked
to past trips ("remember previous travelers" must survive a roster edit).
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Client,
    Itinerary,
    Party,
    PartyMember,
    PartyMemberActor,
    Traveler,
)
from app.schemas.party_members import PartyMemberCreate, PartyMemberUpdate

logger = logging.getLogger("ov_black.party_members")


# ── access resolution (router uses these before mutating) ────────────────


async def load_client_for_advisor(
    session: AsyncSession, *, advisor_id: uuid.UUID, client_id: uuid.UUID
) -> Client | None:
    """The client iff the calling advisor owns it (else None → 404)."""
    return (
        await session.execute(
            select(Client).where(Client.id == client_id, Client.owner_id == advisor_id)
        )
    ).scalar_one_or_none()


# ── member CRUD (client_id already authorized by the caller) ──────────────


async def list_party_members(
    session: AsyncSession, *, client_id: uuid.UUID, include_archived: bool = False
) -> list[PartyMember]:
    """The household's members — active first, primary first, then by name."""
    stmt = select(PartyMember).where(PartyMember.client_id == client_id)
    if not include_archived:
        stmt = stmt.where(PartyMember.archived_at.is_(None))
    stmt = stmt.order_by(
        PartyMember.is_primary.desc(),
        PartyMember.full_name.asc(),
        PartyMember.created_at.asc(),
    )
    return list((await session.execute(stmt)).scalars().all())


async def get_party_member(
    session: AsyncSession, *, client_id: uuid.UUID, member_id: uuid.UUID
) -> PartyMember | None:
    """A member scoped to its client (so a leaked id can't cross households)."""
    return (
        await session.execute(
            select(PartyMember).where(
                PartyMember.id == member_id, PartyMember.client_id == client_id
            )
        )
    ).scalar_one_or_none()


async def _demote_other_primaries(
    session: AsyncSession, *, client_id: uuid.UUID, except_id: uuid.UUID | None = None
) -> None:
    """Clear is_primary on the household's other active members.

    Enforces "one primary per client" cooperatively rather than letting the
    partial unique index raise — setting a new primary simply demotes the old.
    """
    stmt = (
        update(PartyMember)
        .where(
            PartyMember.client_id == client_id,
            PartyMember.is_primary.is_(True),
            PartyMember.archived_at.is_(None),
        )
        .values(is_primary=False, updated_at=datetime.now(UTC))
    )
    if except_id is not None:
        stmt = stmt.where(PartyMember.id != except_id)
    await session.execute(stmt)


async def create_party_member(
    session: AsyncSession,
    *,
    client_id: uuid.UUID,
    payload: PartyMemberCreate,
    actor: PartyMemberActor,
    recorded_by: uuid.UUID | None,
) -> PartyMember:
    """Create a durable member for a client; ``actor`` is fixed by the caller."""
    if payload.is_primary:
        await _demote_other_primaries(session, client_id=client_id)

    member = PartyMember(
        client_id=client_id,
        full_name=payload.full_name,
        date_of_birth=payload.date_of_birth,
        nationality=payload.nationality,
        dietary=payload.dietary,
        medical=payload.medical,
        mobility=payload.mobility,
        loyalty_programs=[lp.model_dump() for lp in payload.loyalty_programs],
        emergency_contact=(
            payload.emergency_contact.model_dump(exclude_none=True)
            if payload.emergency_contact is not None
            else {}
        ),
        relationship_to_primary=payload.relationship_to_primary,
        is_primary=payload.is_primary,
        notes=payload.notes,
        created_by_actor=actor,
        updated_by_actor=actor,
        recorded_by=recorded_by,
    )
    session.add(member)
    await session.flush()
    await session.commit()
    await session.refresh(member)
    return member


async def update_party_member(
    session: AsyncSession,
    *,
    client_id: uuid.UUID,
    member_id: uuid.UUID,
    payload: PartyMemberUpdate,
    actor: PartyMemberActor,
) -> PartyMember | None:
    """Patch a member (only set fields applied); ``actor`` stamps who touched it."""
    member = await get_party_member(session, client_id=client_id, member_id=member_id)
    if member is None:
        return None

    data = payload.model_dump(exclude_unset=True)
    if data.get("is_primary") is True:
        await _demote_other_primaries(session, client_id=client_id, except_id=member.id)

    for field, value in data.items():
        # Nested pydantic models dumped to plain JSON-able structures already.
        setattr(member, field, value)
    member.updated_by_actor = actor
    member.updated_at = datetime.now(UTC)

    await session.flush()
    await session.commit()
    await session.refresh(member)
    return member


async def archive_party_member(
    session: AsyncSession, *, client_id: uuid.UUID, member_id: uuid.UUID
) -> PartyMember | None:
    """Soft-delete: hide from the active roster but keep trip-history links."""
    member = await get_party_member(session, client_id=client_id, member_id=member_id)
    if member is None:
        return None
    if member.archived_at is None:
        now = datetime.now(UTC)
        member.archived_at = now
        member.is_primary = False  # an archived member can't hold the primary slot
        member.updated_at = now
        await session.flush()
        await session.commit()
        await session.refresh(member)
    return member


# ── per-trip participation (attach a durable member to an itinerary) ──────


async def _ensure_default_party(session: AsyncSession, *, itinerary_id: uuid.UUID) -> Party:
    """The itinerary's default ("All travelers") party, created if absent."""
    party = (
        await session.execute(
            select(Party)
            .where(Party.itinerary_id == itinerary_id)
            .order_by(Party.created_at.asc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if party is not None:
        return party
    party = Party(itinerary_id=itinerary_id, label="All travelers")
    session.add(party)
    await session.flush()
    return party


async def attach_member_to_itinerary(
    session: AsyncSession, *, itinerary_id: uuid.UUID, member: PartyMember
) -> Traveler:
    """Put a durable member on an itinerary's party (idempotent per member).

    Returns the existing ``travelers`` row when the member is already attached,
    so re-attaching is a no-op rather than a duplicate.
    """
    existing = (
        await session.execute(
            select(Traveler)
            .join(Party, Party.id == Traveler.party_id)
            .where(
                Party.itinerary_id == itinerary_id,
                Traveler.party_member_id == member.id,
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    party = await _ensure_default_party(session, itinerary_id=itinerary_id)
    traveler = Traveler(
        party_id=party.id,
        party_member_id=member.id,
        name=member.full_name,
    )
    session.add(traveler)
    await session.flush()
    await session.commit()
    await session.refresh(traveler)
    return traveler


async def detach_member_from_itinerary(
    session: AsyncSession, *, itinerary_id: uuid.UUID, member_id: uuid.UUID
) -> bool:
    """Remove a member's per-trip rows from an itinerary. True if anything went."""
    rows = (
        (
            await session.execute(
                select(Traveler)
                .join(Party, Party.id == Traveler.party_id)
                .where(
                    Party.itinerary_id == itinerary_id,
                    Traveler.party_member_id == member_id,
                )
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return False
    for row in rows:
        await session.delete(row)
    await session.commit()
    return True


async def list_itinerary_party(
    session: AsyncSession, *, itinerary_id: uuid.UUID
) -> list[tuple[Traveler, PartyMember | None]]:
    """Every traveler on an itinerary's parties, with its durable member joined."""
    rows = (
        await session.execute(
            select(Traveler, PartyMember)
            .join(Party, Party.id == Traveler.party_id)
            .outerjoin(PartyMember, PartyMember.id == Traveler.party_member_id)
            .where(Party.itinerary_id == itinerary_id)
            .order_by(Traveler.created_at.asc())
        )
    ).all()
    return [(traveler, member) for traveler, member in rows]


async def load_itinerary_client_id(
    session: AsyncSession, *, itinerary_id: uuid.UUID
) -> uuid.UUID | None:
    """The client that owns an itinerary — the spine of the attach authz check."""
    return (
        await session.execute(select(Itinerary.client_id).where(Itinerary.id == itinerary_id))
    ).scalar_one_or_none()
