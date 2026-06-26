"""CRUD + agent-side recording for the three per-fact tiers.

Three tiers, each in its own table with a CHECK-pinned ``source_kind``:

* ``dossier_facts``  — private internal knowledge. ``advisor`` (manual
  command-center entry) or ``agent_inferred`` (recorded by the agent
  during a turn). NEVER revealed to the traveler.
* ``profile_facts``  — traveler self-expression. ``traveler_told`` (the
  agent recorded it after the traveler said it) or ``advisor`` (manual
  attribution). MAY be referenced naturally in conversation.
* ``osint_facts``    — external research. ``scraper`` (a future
  collection job) or ``advisor`` (manual entry). NEVER revealed.

All advisor-side mutations follow the same template: locate the client
under the calling advisor (D015 collapse) → flush a write → commit.
DELETE is a soft-redact (``redacted_at`` stamp); rows survive so the
command center can show "what was here, why it was removed, when".

Agent-side writes go through dedicated entrypoints that pin
``source_kind`` server-side from the endpoint, never the request body —
so a buggy or compromised tool cannot escalate one tier into another
(e.g. a profile-record cannot create an OSINT row).
"""

from __future__ import annotations

import enum
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, TypeVar

from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Client,
    Dossier,
    DossierFact,
    DossierFactKind,
    FactSourceKind,
    OsintFact,
    OsintFactKind,
    PartyMember,
    ProfileFact,
    ProfileFactKind,
)
from app.schemas.facts import (
    DossierFactCreate,
    DossierFactUpdate,
    OsintFactCreate,
    OsintFactUpdate,
    ProfileFactCreate,
    ProfileFactUpdate,
)
from app.services.clients import _load_client_owned_by

logger = logging.getLogger("ov_black.facts")

# Row type of a ``select(...)`` over a single fact model — preserved through
# ``_filter_redacted`` so each tier's statement keeps its concrete row type.
_RowT = TypeVar("_RowT", bound=tuple[Any, ...])


# UUIDv5 namespace seed for deriving ``recorded_by`` from an AgentCore
# session id. Stable across processes; rotating it would orphan the
# linkage between agent-written facts and their session.
_AGENT_RECORDED_BY_NS = uuid.UUID("a9e7b4c0-2f6a-4f11-b3a3-e2a6f4f5a1d2")


class FactOutcome(str, enum.Enum):
    """Terminal states of an advisor fact mutation."""

    OK = "ok"
    CLIENT_NOT_FOUND = "client_not_found"
    FACT_NOT_FOUND = "fact_not_found"
    INVALID_SOURCE_KIND = "invalid_source_kind"


@dataclass(frozen=True, slots=True)
class FactResult:
    outcome: FactOutcome
    fact: DossierFact | ProfileFact | OsintFact | None = None


def _agent_recorded_by(agentcore_session_id: str) -> uuid.UUID:
    """Deterministic UUIDv5 stamp for facts written by the agent.

    Lets the command center group "facts written during session X" without
    introducing a nullable agentcore_session_id column on the fact rows.
    """
    return uuid.uuid5(_AGENT_RECORDED_BY_NS, agentcore_session_id)


# ── Dossier facts ────────────────────────────────────────────────────────


async def create_dossier_fact(
    session: AsyncSession,
    *,
    advisor_id: uuid.UUID,
    client_id: uuid.UUID,
    payload: DossierFactCreate,
) -> FactResult:
    client = await _load_client_owned_by(session, advisor_id=advisor_id, client_id=client_id)
    if client is None:
        return FactResult(FactOutcome.CLIENT_NOT_FOUND)

    fact = DossierFact(
        client_id=client.id,
        kind=payload.kind,
        text=payload.text,
        source_kind=payload.source_kind,
        source_ref=payload.source_ref,
        observed_at=payload.observed_at or datetime.now(UTC),
        recorded_by=advisor_id,
    )
    session.add(fact)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        return FactResult(FactOutcome.INVALID_SOURCE_KIND)
    await session.commit()
    logger.info(
        "facts.dossier.create.ok",
        extra={
            "client_id": str(client.id),
            "advisor_id": str(advisor_id),
            "fact_id": str(fact.id),
            "kind": fact.kind.value,
            "source_kind": fact.source_kind.value,
        },
    )
    return FactResult(FactOutcome.OK, fact=fact)


async def update_dossier_fact(
    session: AsyncSession,
    *,
    advisor_id: uuid.UUID,
    client_id: uuid.UUID,
    fact_id: uuid.UUID,
    payload: DossierFactUpdate,
) -> FactResult:
    client = await _load_client_owned_by(session, advisor_id=advisor_id, client_id=client_id)
    if client is None:
        return FactResult(FactOutcome.CLIENT_NOT_FOUND)

    fact = (
        await session.execute(
            select(DossierFact).where(
                DossierFact.id == fact_id,
                DossierFact.client_id == client.id,
            )
        )
    ).scalar_one_or_none()
    if fact is None:
        return FactResult(FactOutcome.FACT_NOT_FOUND)

    if payload.kind is not None:
        fact.kind = payload.kind
    if payload.text is not None:
        fact.text = payload.text
    fact.updated_at = datetime.now(UTC)
    await session.commit()
    return FactResult(FactOutcome.OK, fact=fact)


async def redact_dossier_fact(
    session: AsyncSession,
    *,
    advisor_id: uuid.UUID,
    client_id: uuid.UUID,
    fact_id: uuid.UUID,
    reason: str,
) -> FactResult:
    client = await _load_client_owned_by(session, advisor_id=advisor_id, client_id=client_id)
    if client is None:
        return FactResult(FactOutcome.CLIENT_NOT_FOUND)

    fact = (
        await session.execute(
            select(DossierFact).where(
                DossierFact.id == fact_id,
                DossierFact.client_id == client.id,
            )
        )
    ).scalar_one_or_none()
    if fact is None or fact.redacted_at is not None:
        return FactResult(FactOutcome.FACT_NOT_FOUND)

    now = datetime.now(UTC)
    fact.redacted_at = now
    fact.redacted_by = advisor_id
    fact.redacted_reason = reason
    fact.updated_at = now
    await session.commit()
    logger.info(
        "facts.dossier.redact.ok",
        extra={
            "client_id": str(client.id),
            "advisor_id": str(advisor_id),
            "fact_id": str(fact.id),
        },
    )
    return FactResult(FactOutcome.OK, fact=fact)


# ── Profile facts ────────────────────────────────────────────────────────


async def create_profile_fact(
    session: AsyncSession,
    *,
    advisor_id: uuid.UUID,
    client_id: uuid.UUID,
    payload: ProfileFactCreate,
) -> FactResult:
    client = await _load_client_owned_by(session, advisor_id=advisor_id, client_id=client_id)
    if client is None:
        return FactResult(FactOutcome.CLIENT_NOT_FOUND)

    fact = ProfileFact(
        client_id=client.id,
        kind=payload.kind,
        text=payload.text,
        source_kind=payload.source_kind,
        source_ref=payload.source_ref,
        observed_at=payload.observed_at or datetime.now(UTC),
        recorded_by=advisor_id,
    )
    session.add(fact)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        return FactResult(FactOutcome.INVALID_SOURCE_KIND)
    await session.commit()
    return FactResult(FactOutcome.OK, fact=fact)


async def update_profile_fact(
    session: AsyncSession,
    *,
    advisor_id: uuid.UUID,
    client_id: uuid.UUID,
    fact_id: uuid.UUID,
    payload: ProfileFactUpdate,
) -> FactResult:
    client = await _load_client_owned_by(session, advisor_id=advisor_id, client_id=client_id)
    if client is None:
        return FactResult(FactOutcome.CLIENT_NOT_FOUND)

    fact = (
        await session.execute(
            select(ProfileFact).where(
                ProfileFact.id == fact_id,
                ProfileFact.client_id == client.id,
            )
        )
    ).scalar_one_or_none()
    if fact is None:
        return FactResult(FactOutcome.FACT_NOT_FOUND)

    if payload.kind is not None:
        fact.kind = payload.kind
    if payload.text is not None:
        fact.text = payload.text
    fact.updated_at = datetime.now(UTC)
    await session.commit()
    return FactResult(FactOutcome.OK, fact=fact)


async def redact_profile_fact(
    session: AsyncSession,
    *,
    advisor_id: uuid.UUID,
    client_id: uuid.UUID,
    fact_id: uuid.UUID,
    reason: str,
) -> FactResult:
    client = await _load_client_owned_by(session, advisor_id=advisor_id, client_id=client_id)
    if client is None:
        return FactResult(FactOutcome.CLIENT_NOT_FOUND)

    fact = (
        await session.execute(
            select(ProfileFact).where(
                ProfileFact.id == fact_id,
                ProfileFact.client_id == client.id,
            )
        )
    ).scalar_one_or_none()
    if fact is None or fact.redacted_at is not None:
        return FactResult(FactOutcome.FACT_NOT_FOUND)

    now = datetime.now(UTC)
    fact.redacted_at = now
    fact.redacted_by = advisor_id
    fact.redacted_reason = reason
    fact.updated_at = now
    await session.commit()
    return FactResult(FactOutcome.OK, fact=fact)


# ── OSINT facts ──────────────────────────────────────────────────────────


async def create_osint_fact(
    session: AsyncSession,
    *,
    advisor_id: uuid.UUID,
    client_id: uuid.UUID,
    payload: OsintFactCreate,
) -> FactResult:
    client = await _load_client_owned_by(session, advisor_id=advisor_id, client_id=client_id)
    if client is None:
        return FactResult(FactOutcome.CLIENT_NOT_FOUND)

    fact = OsintFact(
        client_id=client.id,
        kind=payload.kind,
        text=payload.text,
        source_kind=payload.source_kind,
        source_ref=payload.source_ref,
        observed_at=payload.observed_at or datetime.now(UTC),
        recorded_by=advisor_id,
    )
    session.add(fact)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        return FactResult(FactOutcome.INVALID_SOURCE_KIND)
    await session.commit()
    return FactResult(FactOutcome.OK, fact=fact)


async def update_osint_fact(
    session: AsyncSession,
    *,
    advisor_id: uuid.UUID,
    client_id: uuid.UUID,
    fact_id: uuid.UUID,
    payload: OsintFactUpdate,
) -> FactResult:
    client = await _load_client_owned_by(session, advisor_id=advisor_id, client_id=client_id)
    if client is None:
        return FactResult(FactOutcome.CLIENT_NOT_FOUND)

    fact = (
        await session.execute(
            select(OsintFact).where(
                OsintFact.id == fact_id,
                OsintFact.client_id == client.id,
            )
        )
    ).scalar_one_or_none()
    if fact is None:
        return FactResult(FactOutcome.FACT_NOT_FOUND)

    if payload.kind is not None:
        fact.kind = payload.kind
    if payload.text is not None:
        fact.text = payload.text
    fact.updated_at = datetime.now(UTC)
    await session.commit()
    return FactResult(FactOutcome.OK, fact=fact)


async def redact_osint_fact(
    session: AsyncSession,
    *,
    advisor_id: uuid.UUID,
    client_id: uuid.UUID,
    fact_id: uuid.UUID,
    reason: str,
) -> FactResult:
    client = await _load_client_owned_by(session, advisor_id=advisor_id, client_id=client_id)
    if client is None:
        return FactResult(FactOutcome.CLIENT_NOT_FOUND)

    fact = (
        await session.execute(
            select(OsintFact).where(
                OsintFact.id == fact_id,
                OsintFact.client_id == client.id,
            )
        )
    ).scalar_one_or_none()
    if fact is None or fact.redacted_at is not None:
        return FactResult(FactOutcome.FACT_NOT_FOUND)

    now = datetime.now(UTC)
    fact.redacted_at = now
    fact.redacted_by = advisor_id
    fact.redacted_reason = reason
    fact.updated_at = now
    await session.commit()
    return FactResult(FactOutcome.OK, fact=fact)


# ── Agent-side writes ────────────────────────────────────────────────────


async def record_agent_profile_fact(
    session: AsyncSession,
    *,
    client_id: uuid.UUID,
    agentcore_session_id: str,
    session_id: uuid.UUID,
    kind: ProfileFactKind,
    text: str,
    source_turn_id: uuid.UUID | None,
) -> ProfileFact:
    """Record a fact the traveler **told** the agent.

    Stamps ``source_kind=traveler_told`` server-side; the agent cannot
    override it. ``source_ref`` carries the session + turn linkage so the
    command center can deep-link a fact back to its originating turn.
    """
    fact = ProfileFact(
        client_id=client_id,
        kind=kind,
        text=text,
        source_kind=FactSourceKind.traveler_told,
        source_ref={
            "session_id": str(session_id),
            "agentcore_session_id": agentcore_session_id,
            **({"turn_id": str(source_turn_id)} if source_turn_id else {}),
        },
        observed_at=datetime.now(UTC),
        recorded_by=_agent_recorded_by(agentcore_session_id),
    )
    session.add(fact)
    await session.commit()
    logger.info(
        "facts.profile.agent_record.ok",
        extra={
            "client_id": str(client_id),
            "session_id": str(session_id),
            "fact_id": str(fact.id),
            "kind": fact.kind.value,
        },
    )
    return fact


async def record_agent_dossier_inference(
    session: AsyncSession,
    *,
    client_id: uuid.UUID,
    agentcore_session_id: str,
    session_id: uuid.UUID,
    kind: DossierFactKind,
    text: str,
    source_turn_id: uuid.UUID | None,
) -> DossierFact:
    """Record a private inference the agent made about the traveler.

    Stamps ``source_kind=agent_inferred`` server-side. The fact lives in
    the Dossier tier and must NEVER be revealed to the traveler — same
    discipline as advisor-seeded dossier facts.
    """
    fact = DossierFact(
        client_id=client_id,
        kind=kind,
        text=text,
        source_kind=FactSourceKind.agent_inferred,
        source_ref={
            "session_id": str(session_id),
            "agentcore_session_id": agentcore_session_id,
            **({"turn_id": str(source_turn_id)} if source_turn_id else {}),
        },
        observed_at=datetime.now(UTC),
        recorded_by=_agent_recorded_by(agentcore_session_id),
    )
    session.add(fact)
    await session.commit()
    logger.info(
        "facts.dossier.agent_record.ok",
        extra={
            "client_id": str(client_id),
            "session_id": str(session_id),
            "fact_id": str(fact.id),
            "kind": fact.kind.value,
        },
    )
    return fact


# ── Read aggregation ─────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class TravelerContextRows:
    """Aggregate of every row the agent or command center needs in one call.

    Returned by :func:`load_agent_context`. The transport schemas
    (``AgentContext``, ``ClientDetail``) wrap this with their own field
    names; this dataclass is deliberately the database-shaped tuple.
    """

    client: Client
    dossier: Dossier | None
    dossier_facts: list[DossierFact]
    profile_facts: list[ProfileFact]
    osint_facts: list[OsintFact]
    party_members: list[PartyMember] = field(default_factory=list)


async def load_agent_context(
    session: AsyncSession,
    *,
    client_id: uuid.UUID,
    include_redacted: bool = False,
) -> TravelerContextRows | None:
    """Gather the client + dossier + active facts in three small queries.

    Returns ``None`` if the client row does not exist. ``include_redacted``
    is for the advisor-facing detail surface; agent-facing callers should
    pass the default (``False``) so the prompt never sees redacted facts.
    """
    client = (
        await session.execute(select(Client).where(Client.id == client_id))
    ).scalar_one_or_none()
    if client is None:
        return None

    dossier = (
        await session.execute(select(Dossier).where(Dossier.client_id == client_id))
    ).scalar_one_or_none()

    def _filter_redacted(stmt: Select[_RowT], model: type[Any]) -> Select[_RowT]:
        if include_redacted:
            return stmt
        return stmt.where(model.redacted_at.is_(None))

    dossier_facts = list(
        (
            await session.execute(
                _filter_redacted(
                    select(DossierFact)
                    .where(DossierFact.client_id == client_id)
                    .order_by(DossierFact.observed_at.desc()),
                    DossierFact,
                )
            )
        )
        .scalars()
        .all()
    )
    profile_facts = list(
        (
            await session.execute(
                _filter_redacted(
                    select(ProfileFact)
                    .where(ProfileFact.client_id == client_id)
                    .order_by(ProfileFact.observed_at.desc()),
                    ProfileFact,
                )
            )
        )
        .scalars()
        .all()
    )
    osint_facts = list(
        (
            await session.execute(
                _filter_redacted(
                    select(OsintFact)
                    .where(OsintFact.client_id == client_id)
                    .order_by(OsintFact.observed_at.desc()),
                    OsintFact,
                )
            )
        )
        .scalars()
        .all()
    )

    # Active household members (0019) — the durable party the agent should know
    # about ("remember previous travelers"). Primary first, then by name.
    party_members = list(
        (
            await session.execute(
                select(PartyMember)
                .where(
                    PartyMember.client_id == client_id,
                    PartyMember.archived_at.is_(None),
                )
                .order_by(
                    PartyMember.is_primary.desc(),
                    PartyMember.full_name.asc(),
                )
            )
        )
        .scalars()
        .all()
    )

    return TravelerContextRows(
        client=client,
        dossier=dossier,
        dossier_facts=dossier_facts,
        profile_facts=profile_facts,
        osint_facts=osint_facts,
        party_members=party_members,
    )


# Re-export the kind enums so router modules can import them via
# ``from app.services.facts import ...`` without reaching into models.
__all__ = [
    "FactOutcome",
    "FactResult",
    "TravelerContextRows",
    "create_dossier_fact",
    "update_dossier_fact",
    "redact_dossier_fact",
    "create_profile_fact",
    "update_profile_fact",
    "redact_profile_fact",
    "create_osint_fact",
    "update_osint_fact",
    "redact_osint_fact",
    "record_agent_profile_fact",
    "record_agent_dossier_inference",
    "load_agent_context",
    "DossierFactKind",
    "OsintFactKind",
    "ProfileFactKind",
]
