"""Party member service (M003/V1) — durable identity + per-trip reuse.

Integration tests (gated on local Supabase). They exercise the behaviours that
make a member *durable* and *collaborative*: client-scoped CRUD, one-primary
enforcement, soft-archive, attach/detach onto a trip, the same member reused
across two itineraries ("remember previous travelers"), and the agent-context
read that surfaces the active roster.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest_asyncio
from app.models import Client, PartyMemberActor
from app.schemas.party_members import (
    EmergencyContact,
    LoyaltyProgram,
    PartyMemberCreate,
    PartyMemberUpdate,
)
from app.services.facts import load_agent_context
from app.services.party_members import (
    archive_party_member,
    attach_member_to_itinerary,
    create_party_member,
    detach_member_from_itinerary,
    get_party_member,
    list_itinerary_party,
    list_party_members,
    update_party_member,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tests._graph_seed import LOCAL_DB_URL, insert_itinerary, integration

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

pytestmark = integration


@pytest_asyncio.fixture()
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(LOCAL_DB_URL, pool_pre_ping=True, future=True)
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with maker() as s:
            yield s
    finally:
        await engine.dispose()


class _Household:
    def __init__(self, advisor_id: uuid.UUID, traveler_id: uuid.UUID, client_id: uuid.UUID) -> None:
        self.advisor_id = advisor_id
        self.traveler_id = traveler_id
        self.client_id = client_id


async def _insert_auth_user(session: AsyncSession, user_id: uuid.UUID, email: str) -> None:
    await session.execute(
        text(
            """
            insert into auth.users (id, email, aud, role, instance_id)
            values (:id, :email, 'authenticated', 'authenticated',
                    '00000000-0000-0000-0000-000000000000')
            """
        ),
        {"id": user_id, "email": email},
    )


@pytest_asyncio.fixture()
async def household(session: AsyncSession) -> AsyncIterator[_Household]:
    advisor_id = uuid.uuid4()
    traveler_id = uuid.uuid4()
    await _insert_auth_user(session, advisor_id, f"adv-{advisor_id.hex[:8]}@example.com")
    await _insert_auth_user(session, traveler_id, f"trv-{traveler_id.hex[:8]}@example.com")
    client = Client(
        owner_id=advisor_id,
        auth_user_id=traveler_id,
        full_name="Household Head",
        email=f"head-{advisor_id.hex[:8]}@example.com",
    )
    session.add(client)
    await session.commit()
    await session.refresh(client)
    cid = client.id
    try:
        yield _Household(advisor_id, traveler_id, cid)
    finally:
        # itineraries → parties → travelers cascade; clients → party_members cascade.
        await session.execute(
            text("delete from public.itineraries where client_id = :cid"), {"cid": cid}
        )
        await session.execute(text("delete from public.clients where id = :cid"), {"cid": cid})
        await session.execute(
            text("delete from auth.users where id = any(:ids)"),
            {"ids": [advisor_id, traveler_id]},
        )
        await session.commit()


def _create(full_name: str, **kw: object) -> PartyMemberCreate:
    return PartyMemberCreate(full_name=full_name, **kw)  # type: ignore[arg-type]


async def test_create_persists_fields_and_lists_primary_first(
    session: AsyncSession, household: _Household
) -> None:
    await create_party_member(
        session,
        client_id=household.client_id,
        payload=_create(
            "Avery Stone",
            is_primary=True,
            dietary="shellfish allergy",
            loyalty_programs=[LoyaltyProgram(program="ANA", number="X1")],
            emergency_contact=EmergencyContact(name="Pat", phone="+1 555 0100"),
        ),
        actor=PartyMemberActor.advisor,
        recorded_by=household.advisor_id,
    )
    await create_party_member(
        session,
        client_id=household.client_id,
        payload=_create("Wren Stone", relationship_to_primary="spouse"),
        actor=PartyMemberActor.advisor,
        recorded_by=household.advisor_id,
    )

    members = await list_party_members(session, client_id=household.client_id)
    assert [m.full_name for m in members] == ["Avery Stone", "Wren Stone"]  # primary first
    primary = members[0]
    assert primary.is_primary is True
    assert primary.dietary == "shellfish allergy"
    assert primary.loyalty_programs == [{"program": "ANA", "number": "X1"}]
    assert primary.emergency_contact == {"name": "Pat", "phone": "+1 555 0100"}
    assert primary.created_by_actor is PartyMemberActor.advisor


async def test_only_one_active_primary_per_client(
    session: AsyncSession, household: _Household
) -> None:
    first = await create_party_member(
        session,
        client_id=household.client_id,
        payload=_create("First Primary", is_primary=True),
        actor=PartyMemberActor.advisor,
        recorded_by=household.advisor_id,
    )
    await create_party_member(
        session,
        client_id=household.client_id,
        payload=_create("Second Primary", is_primary=True),
        actor=PartyMemberActor.traveler,
        recorded_by=household.traveler_id,
    )
    members = await list_party_members(session, client_id=household.client_id)
    primaries = [m for m in members if m.is_primary]
    assert len(primaries) == 1
    assert primaries[0].full_name == "Second Primary"
    # the original was demoted, not deleted
    demoted = await get_party_member(session, client_id=household.client_id, member_id=first.id)
    assert demoted is not None and demoted.is_primary is False


async def test_update_applies_only_set_fields_and_stamps_actor(
    session: AsyncSession, household: _Household
) -> None:
    member = await create_party_member(
        session,
        client_id=household.client_id,
        payload=_create("Edit Me", nationality="US"),
        actor=PartyMemberActor.advisor,
        recorded_by=household.advisor_id,
    )
    updated = await update_party_member(
        session,
        client_id=household.client_id,
        member_id=member.id,
        payload=PartyMemberUpdate(dietary="vegetarian"),
        actor=PartyMemberActor.traveler,
    )
    assert updated is not None
    assert updated.dietary == "vegetarian"
    assert updated.nationality == "US"  # untouched field preserved
    assert updated.full_name == "Edit Me"
    assert updated.updated_by_actor is PartyMemberActor.traveler
    assert updated.created_by_actor is PartyMemberActor.advisor


async def test_archive_soft_deletes_and_hides_from_active(
    session: AsyncSession, household: _Household
) -> None:
    member = await create_party_member(
        session,
        client_id=household.client_id,
        payload=_create("Departing Guest", is_primary=True),
        actor=PartyMemberActor.advisor,
        recorded_by=household.advisor_id,
    )
    archived = await archive_party_member(
        session, client_id=household.client_id, member_id=member.id
    )
    assert archived is not None
    assert archived.archived_at is not None
    assert archived.is_primary is False  # archived can't hold the primary slot

    active = await list_party_members(session, client_id=household.client_id)
    assert member.id not in {m.id for m in active}
    with_archived = await list_party_members(
        session, client_id=household.client_id, include_archived=True
    )
    assert member.id in {m.id for m in with_archived}


async def test_get_member_is_client_scoped(
    session: AsyncSession, household: _Household
) -> None:
    member = await create_party_member(
        session,
        client_id=household.client_id,
        payload=_create("Private Person"),
        actor=PartyMemberActor.advisor,
        recorded_by=household.advisor_id,
    )
    # A different (random) client id must not resolve this member.
    stranger = await get_party_member(
        session, client_id=uuid.uuid4(), member_id=member.id
    )
    assert stranger is None


async def test_member_is_reused_across_two_itineraries(
    session: AsyncSession, household: _Household
) -> None:
    """The 'remember previous travelers' invariant: one member, many trips."""
    member = await create_party_member(
        session,
        client_id=household.client_id,
        payload=_create("Returning Traveler", dietary="no gluten"),
        actor=PartyMemberActor.advisor,
        recorded_by=household.advisor_id,
    )
    trip_a = await insert_itinerary(session, client_id=household.client_id)
    trip_b = await insert_itinerary(session, client_id=household.client_id)

    t1 = await attach_member_to_itinerary(session, itinerary_id=trip_a, member=member)
    # re-attach is idempotent — same traveler row, no duplicate
    t1_again = await attach_member_to_itinerary(session, itinerary_id=trip_a, member=member)
    assert t1.id == t1_again.id
    t2 = await attach_member_to_itinerary(session, itinerary_id=trip_b, member=member)
    assert t2.id != t1.id  # a distinct per-trip row on the second itinerary

    party_a = await list_itinerary_party(session, itinerary_id=trip_a)
    party_b = await list_itinerary_party(session, itinerary_id=trip_b)
    assert [m.id for _, m in party_a if m] == [member.id]
    assert [m.id for _, m in party_b if m] == [member.id]
    # both per-trip rows resolve to the SAME durable member
    assert party_a[0][0].party_member_id == member.id
    assert party_b[0][0].party_member_id == member.id

    # detaching from trip A leaves trip B intact
    assert await detach_member_from_itinerary(
        session, itinerary_id=trip_a, member_id=member.id
    )
    assert await list_itinerary_party(session, itinerary_id=trip_a) == []
    assert len(await list_itinerary_party(session, itinerary_id=trip_b)) == 1


async def test_member_constraints_flow_into_fill(
    session: AsyncSession, household: _Household
) -> None:
    """A dietary/mobility entered on a saved member is what Fill scores against."""
    from app.services.fill import _party_constraints

    member = await create_party_member(
        session,
        client_id=household.client_id,
        payload=_create(
            "Constrained Guest", dietary="tree-nut allergy", mobility="wheelchair user"
        ),
        actor=PartyMemberActor.advisor,
        recorded_by=household.advisor_id,
    )
    trip = await insert_itinerary(session, client_id=household.client_id)
    traveler = await attach_member_to_itinerary(session, itinerary_id=trip, member=member)

    allergens, has_mobility_limit = await _party_constraints(session, traveler.party_id)
    assert "tree-nut" in allergens  # parsed from the member's free-text dietary
    assert has_mobility_limit is True


async def test_agent_context_surfaces_active_roster_only(
    session: AsyncSession, household: _Household
) -> None:
    await create_party_member(
        session,
        client_id=household.client_id,
        payload=_create("On The Trip", is_primary=True),
        actor=PartyMemberActor.agent,
        recorded_by=None,
    )
    gone = await create_party_member(
        session,
        client_id=household.client_id,
        payload=_create("No Longer Coming"),
        actor=PartyMemberActor.advisor,
        recorded_by=household.advisor_id,
    )
    await archive_party_member(session, client_id=household.client_id, member_id=gone.id)

    ctx = await load_agent_context(session, client_id=household.client_id)
    assert ctx is not None
    names = {m.full_name for m in ctx.party_members}
    assert names == {"On The Trip"}
    assert ctx.party_members[0].created_by_actor is PartyMemberActor.agent
