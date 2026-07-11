"""Per-user self-service surface.

``GET /me/client`` resolves the ``clients`` row that belongs to the calling
Supabase user, performing a JIT backfill of ``clients.auth_user_id`` when the
link is still missing. It exists so the web ``/auth/callback`` route can
discover where to redirect a freshly magic-linked invitee: RLS on
``public.clients`` only allows advisors to select rows they own, so clients
can't answer this question against Supabase directly.

``GET /me/itineraries`` gives the Bedrock AgentCore agent read access to
the calling client's own itineraries. The agent forwards the client's
Supabase JWT when it invokes tools, so the same routes serve both the
client's own browser and the agent acting on their behalf.

Dossier and OSINT are intentionally NOT exposed here — those are private
to the advisor and never readable by the traveler. The agent reads them
via ``GET /agent/context`` using a per-session agent token issued at
``POST /sessions``; that path bypasses Supabase JWT auth entirely.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import case, func, select
from sqlalchemy.orm import aliased

from app.auth import AuthenticatedUser, require_user
from app.db import get_session
from app.models import (
    AgentSession,
    AgentTurn,
    ForkStatus,
    InvoiceStatus,
    Itinerary,
    ItineraryTimingKind,
    Node,
    NodeStatus,
    NodeType,
    ProfileFact,
    SessionAudience,
    TurnRole,
)
from app.services import invoices as invoices_svc
from app.services.clients import resolve_client_for_auth_user
from app.services.display_status import DisplayStatus, display_status_expr

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


logger = logging.getLogger("ov_black.routers.me")

router = APIRouter(prefix="/me", tags=["me"])


class MyClientResponse(BaseModel):
    """Response for ``GET /me/client`` — the client_id the caller belongs to."""

    client_id: uuid.UUID


class MyItinerarySummary(BaseModel):
    """Row shape for ``GET /me/itineraries``."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    # Derived trunk lifecycle bucket (in_studio / with_traveler / approved).
    status: DisplayStatus
    created_at: datetime
    updated_at: datetime
    # True when the caller has their own OPEN fork of this trunk — the solo
    # traveler's working copy. Basecamp uses it to label an empty trunk "your
    # working version" instead of the advisor-is-crafting teaser.
    has_open_fork: bool = False
    # Trip timeframe for the basecamp tile subtitle. Sourced from the trunk,
    # falling back to the caller's open fork — a solo traveler sets the dates in
    # their working copy while the trunk is still empty. ``timing_kind`` tells the
    # tile whether a real range exists (``exact``/``window``) or the trip is still
    # ``flexible`` (show the target ``duration_nights`` instead).
    date_start: date | None = None
    date_end: date | None = None
    timing_kind: ItineraryTimingKind | None = None
    duration_nights: int | None = None
    # A representative hero image for the tile, pulled from the trip's most
    # evocative node (destination → hotel → experience → meal). ``cover_image``
    # is a ready-to-use URL (inventory snapshot / ambient); ``cover_photo_token``
    # is a signed Google Places token the browser turns into a proxied URL via
    # ``placePhotoUrl`` (the same path the node cards use). At most one is set;
    # both null → the tile falls back to its gradient placeholder.
    cover_image: str | None = None
    cover_photo_token: str | None = None


class MyItinerariesResponse(BaseModel):
    """Envelope for ``GET /me/itineraries``."""

    model_config = ConfigDict(from_attributes=True)

    itineraries: list[MyItinerarySummary]


# Node kinds that carry evocative imagery, in the order we'd rather hero on a
# basecamp tile: a destination shot beats a hotel, which beats an experience,
# which beats a meal. Transit / notes / free-time never carry a cover.
_COVER_NODE_TYPES = (
    NodeType.destination,
    NodeType.hotel,
    NodeType.experience,
    NodeType.meal,
)


def _extract_cover(metadata: dict[str, Any]) -> tuple[str | None, str | None]:
    """Pull ``(cover_image, photo_token)`` from a node's metadata blob.

    Mirrors the priority the node cards render with: a signed Places
    ``photo_token`` (proxied client-side) or a ready ``snapshot.cover_image`` /
    ``ambient_image`` URL. Returns ``(None, None)`` when the node has neither.
    """
    snapshot = metadata.get("snapshot")
    cover_image = snapshot.get("cover_image") if isinstance(snapshot, dict) else None
    if not cover_image:
        cover_image = metadata.get("ambient_image")
    place = metadata.get("place")
    photo_token = place.get("photo_token") if isinstance(place, dict) else None
    cover_image = cover_image if isinstance(cover_image, str) and cover_image else None
    photo_token = photo_token if isinstance(photo_token, str) and photo_token else None
    return cover_image, photo_token


async def _cover_images_by_trunk(
    session: AsyncSession,
    id_to_trunk: dict[uuid.UUID, uuid.UUID],
) -> dict[uuid.UUID, tuple[str | None, str | None]]:
    """Choose one hero image per trunk from its (and its fork's) content nodes.

    ``id_to_trunk`` maps every content-bearing itinerary id — each trunk plus
    the caller's open fork of it — back to the trunk the tile keys off, so a
    solo traveler whose nodes live only in their fork still gets a cover. Nodes
    are scanned in cover-preference order (see ``_COVER_NODE_TYPES``) and the
    first image-bearing node wins per trunk.
    """
    if not id_to_trunk:
        return {}
    type_pref = case(
        *((Node.type == kind, i) for i, kind in enumerate(_COVER_NODE_TYPES)),
        else_=len(_COVER_NODE_TYPES),
    )
    rows = (
        await session.execute(
            select(Node.itinerary_id, Node.metadata_)
            .where(
                Node.itinerary_id.in_(list(id_to_trunk.keys())),
                Node.deleted_at.is_(None),
                Node.status != NodeStatus.discarded,
                Node.type.in_(_COVER_NODE_TYPES),
            )
            .order_by(type_pref, Node.created_at)
        )
    ).all()
    covers: dict[uuid.UUID, tuple[str | None, str | None]] = {}
    for itin_id, metadata in rows:
        trunk_id = id_to_trunk.get(itin_id)
        if trunk_id is None or trunk_id in covers:
            continue
        cover_image, photo_token = _extract_cover(metadata or {})
        if cover_image or photo_token:
            covers[trunk_id] = (cover_image, photo_token)
    return covers


class MyInvoiceSummary(BaseModel):
    """Row shape for ``GET /me/invoices`` — one invoice across any of the trips."""

    id: uuid.UUID
    label: str
    status: InvoiceStatus
    currency: str
    total: Decimal
    due_at: datetime | None
    itinerary_id: uuid.UUID
    itinerary_title: str


class MyInvoicesResponse(BaseModel):
    """Envelope for ``GET /me/invoices``."""

    invoices: list[MyInvoiceSummary]


def evaluate_onboarding(*, profile_fact_count: int) -> bool:
    """The single, swappable "do we know enough about this traveler?" rule.

    Today it's satisfied by two things the traveler told us about themselves
    (two non-redacted ``profile_facts`` rows). This is deliberately the ONLY
    place the criterion lives: the basecamp reminder and the in-chat milestone
    card both key off its result (exposed as ``onboarding_complete``), so
    moving the bar — e.g. adding a known-age requirement — is a change to this
    function alone, with no caller or UI edits. Keep the *inputs* explicit
    (add parameters like ``age_known`` as the rule grows) rather than reaching
    into globals, so the rule stays unit-testable in isolation.
    """
    return profile_fact_count >= 2


class MyOnboardingSessionResponse(BaseModel):
    """Summary of the calling client's most-recent ACTIVE agent session.

    ``session_id`` (and the dependent fields ``turn_count``,
    ``last_turn_at``, ``seeded_opener``) describe the current ongoing
    session — i.e. ``ended_at IS NULL``. ``has_prior_session`` is true
    iff the client has any session row at all, ended or not. Basecamp
    uses ``has_prior_session`` (rather than ``turn_count > 0``) to gate
    the first-prompt opener UI so a user who clicks Skip / Close is not
    re-shown the opener on the next page load.

    ``onboarding_complete`` is the single "do we know enough about this
    traveler yet?" verdict, computed by :func:`evaluate_onboarding` — the
    ONE place that rule lives. Basecamp combines it with the variant to
    decide the onboarding nudge: a client in the ``post_first_touch``
    state (a session exists, but no itinerary yet) who is **not** yet
    onboarding-complete skipped before we learned enough, so basecamp
    shows a gentle reminder; the in-chat milestone card fires on the same
    verdict flipping true. Because both surfaces read this one derived
    field, evolving the rule (e.g. to require two facts plus a known age)
    touches only ``evaluate_onboarding``.

    All session-scoped fields are null when no active session exists.
    """

    model_config = ConfigDict(extra="forbid")

    session_id: uuid.UUID | None
    turn_count: int
    last_turn_at: datetime | None
    seeded_opener: str | None
    has_prior_session: bool
    onboarding_complete: bool


@router.get(
    "/client",
    response_model=MyClientResponse,
    responses={
        404: {"description": "No client row is linked to this user."},
    },
    summary="Resolve the client_id for the calling user (invitee chat entry).",
)
async def get_my_client_endpoint(
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> MyClientResponse:
    try:
        user_id = uuid.UUID(user.sub)
    except ValueError:  # pragma: no cover — Supabase subs are always UUIDs
        logger.warning("me.client.malformed_sub", extra={"sub_hint": user.sub[:8]})
        raise HTTPException(status_code=404, detail="client_not_found") from None

    client = await resolve_client_for_auth_user(session, user_id=user_id, email=user.email)
    if client is None:
        raise HTTPException(status_code=404, detail="client_not_found")
    return MyClientResponse(client_id=client.id)


@router.get(
    "/itineraries",
    response_model=MyItinerariesResponse,
    summary="List the calling client's itineraries — draft + approved.",
)
async def list_my_itineraries_endpoint(
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> MyItinerariesResponse:
    """Return the OFFICIAL itineraries (baselines) for the caller's client row.

    Needed for Q&A mode where the agent may need to enumerate the client's
    trips ("which trip is next?") before drilling into a specific graph.
    Forks (the traveler's private "My version" of a trip) are excluded — they
    are reached via the two-version toggle on the itinerary page, not listed as
    standalone trips. Orders newest-updated first. Empty list is a valid
    response — a client in onboarding has no itineraries yet.
    """
    try:
        user_id = uuid.UUID(user.sub)
    except ValueError:  # pragma: no cover
        return MyItinerariesResponse(itineraries=[])

    client = await resolve_client_for_auth_user(session, user_id=user_id, email=user.email)
    if client is None:
        return MyItinerariesResponse(itineraries=[])

    # Only OFFICIAL itineraries (trunks) list here. A fork is the traveler's
    # private "My version" of a trip — reached via the two-version toggle on the
    # itinerary page, never shown as a standalone trip card on basecamp.
    #
    # BUT for a solo traveler the trip's title/dates and all its nodes live in
    # that private fork (their working copy) — the trunk stays empty until an
    # advisor publishes, and reconcile only folds *node* changes, never the
    # trip-level title. So we LEFT JOIN the caller's own open fork and surface
    # its title / freshness as a fallback: the card shows "Patagonia on Foot"
    # (from the fork) instead of the empty-trunk "Your itinerary" placeholder,
    # while still keying and linking off the trunk id.
    # One row per trunk: DISTINCT ON collapses a caller's several open forks of
    # the same trunk to just the newest, so the LEFT JOIN can't fan a trunk out
    # into duplicate cards.
    fork = aliased(Itinerary)
    open_fork = (
        select(
            fork.forked_from_id.label("trunk_id"),
            fork.id.label("fork_id"),
            fork.title.label("fork_title"),
            fork.updated_at.label("fork_updated_at"),
            fork.date_start.label("fork_date_start"),
            fork.date_end.label("fork_date_end"),
            fork.timing_kind.label("fork_timing_kind"),
            fork.duration_nights.label("fork_duration_nights"),
        )
        .where(
            fork.fork_status == ForkStatus.open,
            fork.created_by == user_id,
        )
        .distinct(fork.forked_from_id)
        .order_by(fork.forked_from_id, fork.updated_at.desc())
        .subquery()
    )
    rows = (
        await session.execute(
            select(
                Itinerary,
                display_status_expr(),
                open_fork.c.fork_id,
                open_fork.c.fork_title,
                open_fork.c.fork_updated_at,
                open_fork.c.fork_date_start,
                open_fork.c.fork_date_end,
                open_fork.c.fork_timing_kind,
                open_fork.c.fork_duration_nights,
            )
            .outerjoin(open_fork, open_fork.c.trunk_id == Itinerary.id)
            .where(
                Itinerary.client_id == client.id,
                Itinerary.forked_from_id.is_(None),
            )
            .order_by(Itinerary.updated_at.desc())
        )
    ).all()

    # Map every content-bearing itinerary (each trunk + the caller's fork of it)
    # back to its trunk, then pick one hero image per trunk in a single query.
    id_to_trunk: dict[uuid.UUID, uuid.UUID] = {}
    for row in rows:
        id_to_trunk[row[0].id] = row[0].id
        if row.fork_id is not None:
            id_to_trunk[row.fork_id] = row[0].id
    covers = await _cover_images_by_trunk(session, id_to_trunk)

    return MyItinerariesResponse(
        itineraries=[
            MyItinerarySummary(
                id=row.id,
                # Prefer the trunk's own title once it has one (published), else
                # fall back to the caller's open-fork working copy.
                title=row.title or (fork_title or ""),
                status=DisplayStatus(bucket),
                created_at=row.created_at,
                # A solo traveler edits the fork, not the trunk — so the fork's
                # timestamp is the meaningful "last touched" when it's newer.
                updated_at=max(row.updated_at, fork_updated_at)
                if fork_updated_at is not None
                else row.updated_at,
                has_open_fork=fork_id is not None,
                # Timing: trunk wins once set, else the fork's working copy.
                date_start=row.date_start or fork_date_start,
                date_end=row.date_end or fork_date_end,
                timing_kind=row.timing_kind or fork_timing_kind,
                duration_nights=row.duration_nights or fork_duration_nights,
                cover_image=covers.get(row.id, (None, None))[0],
                cover_photo_token=covers.get(row.id, (None, None))[1],
            )
            for (
                row,
                bucket,
                fork_id,
                fork_title,
                fork_updated_at,
                fork_date_start,
                fork_date_end,
                fork_timing_kind,
                fork_duration_nights,
            ) in rows
        ]
    )


@router.get(
    "/invoices",
    response_model=MyInvoicesResponse,
    summary="List the calling client's invoices across all itineraries.",
)
async def list_my_invoices_endpoint(
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> MyInvoicesResponse:
    """Every invoice across the caller's trips, newest first.

    Owner-scoped via ``resolve_client_for_auth_user`` (the same self-scoping as
    ``/me/itineraries``), so a traveler only ever sees their own client's
    invoices. Empty list is valid. Each row links to the existing
    ``/invoices/{id}`` pay page.
    """
    try:
        user_id = uuid.UUID(user.sub)
    except ValueError:  # pragma: no cover
        return MyInvoicesResponse(invoices=[])

    client = await resolve_client_for_auth_user(session, user_id=user_id, email=user.email)
    if client is None:
        return MyInvoicesResponse(invoices=[])

    rows = await invoices_svc.list_invoices_for_client(session, client.id)
    return MyInvoicesResponse(
        invoices=[
            MyInvoiceSummary(
                id=view.invoice.id,
                label=view.invoice.label,
                status=view.invoice.status,
                currency=view.invoice.currency,
                total=view.total,
                due_at=view.invoice.due_at,
                itinerary_id=itin.id,
                itinerary_title=itin.title,
            )
            for view, itin in rows
        ]
    )


@router.get(
    "/onboarding_session",
    response_model=MyOnboardingSessionResponse,
    summary="Summarize the calling client's most-recent agent session.",
)
async def get_my_onboarding_session_endpoint(
    user: AuthenticatedUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
) -> MyOnboardingSessionResponse:
    """Return ``{session_id, turn_count, last_turn_at, seeded_opener}`` or all-null.

    Powers basecamp's "have we conversed yet?" decision: if ``turn_count``
    is zero we render the single-prompt opener UI; otherwise we render the
    persistent right-rail chat invite. Basecamp is a traveler-facing
    surface, so this is scoped to ``audience == traveler`` — an advisor
    session opened about this client (Command Center) must never leak into
    basecamp, or the traveler's chat would POST turns to a session the
    existence-hiding authz collapses to 404.

    Scope is ALSO ``itinerary_id IS NULL`` — the basecamp (unpinned) session.
    Since PS2 made session reuse itinerary-scoped, a traveler's itinerary-pinned
    Artemis chat is a *different, newer* session; without this filter the newest
    traveler session (an itinerary chat) would surface on basecamp, so the rail
    would show "your chat from the itinerary" instead of the basecamp thread.
    """
    empty = MyOnboardingSessionResponse(
        session_id=None,
        turn_count=0,
        last_turn_at=None,
        seeded_opener=None,
        has_prior_session=False,
        onboarding_complete=False,
    )
    try:
        user_id = uuid.UUID(user.sub)
    except ValueError:  # pragma: no cover
        return empty

    client = await resolve_client_for_auth_user(session, user_id=user_id, email=user.email)
    if client is None:
        return empty

    # Count the client's non-redacted profile facts (soft-deleted rows excluded,
    # matching the active-fact filter in services/facts.py) and feed it to the
    # ONE onboarding rule. The bool it returns — never the raw count — drives
    # both the nudge and the milestone card.
    profile_fact_count = int(
        (
            await session.execute(
                select(func.count(ProfileFact.id)).where(
                    ProfileFact.client_id == client.id,
                    ProfileFact.redacted_at.is_(None),
                )
            )
        ).scalar_one()
    )
    onboarding_complete = evaluate_onboarding(profile_fact_count=profile_fact_count)

    # Has-prior is independent of active/ended status — it gates the
    # first-prompt opener UI so a Skip / Close click is not re-prompted
    # on the next basecamp visit.
    has_prior_session = bool(
        (
            await session.execute(
                select(func.count(AgentSession.id)).where(
                    AgentSession.client_id == client.id,
                    AgentSession.audience == SessionAudience.traveler,
                    AgentSession.itinerary_id.is_(None),
                )
            )
        ).scalar_one()
    )

    agent_session = (
        await session.execute(
            select(AgentSession)
            .where(
                AgentSession.client_id == client.id,
                AgentSession.audience == SessionAudience.traveler,
                AgentSession.itinerary_id.is_(None),
                AgentSession.ended_at.is_(None),
            )
            .order_by(AgentSession.started_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if agent_session is None:
        return MyOnboardingSessionResponse(
            session_id=None,
            turn_count=0,
            last_turn_at=None,
            seeded_opener=None,
            has_prior_session=has_prior_session,
            onboarding_complete=onboarding_complete,
        )

    summary = (
        await session.execute(
            select(
                func.count(AgentTurn.id),
                func.max(AgentTurn.created_at),
            ).where(
                AgentTurn.session_id == agent_session.id,
                AgentTurn.role.in_((TurnRole.user, TurnRole.assistant)),
            )
        )
    ).one()
    turn_count = int(summary[0] or 0)
    last_turn_at = summary[1]

    return MyOnboardingSessionResponse(
        session_id=agent_session.id,
        turn_count=turn_count,
        last_turn_at=last_turn_at,
        seeded_opener=agent_session.seeded_opener,
        has_prior_session=has_prior_session,
        onboarding_complete=onboarding_complete,
    )
