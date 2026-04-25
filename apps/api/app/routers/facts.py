"""Advisor fact-CRUD surface for the three per-fact tiers.

Three triplets of routes, all gated by ``require_advisor`` and scoped to
clients the calling advisor owns (``_load_client_owned_by`` 404s on
cross-advisor — D015 collapsed shape):

- ``POST   /clients/{cid}/dossier/facts``
  ``PATCH  /clients/{cid}/dossier/facts/{fid}``
  ``DELETE /clients/{cid}/dossier/facts/{fid}``  (soft-redact, body=``RedactRequest``)

- ``POST/PATCH/DELETE /clients/{cid}/profile/facts[/{fid}]``
- ``POST/PATCH/DELETE /clients/{cid}/osint/facts[/{fid}]``

DELETE is a soft-redact (stamps ``redacted_at/by/reason``); rows survive
so the command center can show the redaction history. ``GET`` is not
exposed on this router — facts come back inside ``GET /clients/{id}``,
which already has a single point of access scoping + ``include_redacted``.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AuthenticatedUser
from app.auth_guards import require_advisor
from app.db import get_session
from app.routers.clients import _advisor_id
from app.schemas.facts import (
    DossierFactCreate,
    DossierFactDetail,
    DossierFactUpdate,
    OsintFactCreate,
    OsintFactDetail,
    OsintFactUpdate,
    ProfileFactCreate,
    ProfileFactDetail,
    ProfileFactUpdate,
    RedactRequest,
)
from app.services.facts import (
    FactOutcome,
    create_dossier_fact,
    create_osint_fact,
    create_profile_fact,
    redact_dossier_fact,
    redact_osint_fact,
    redact_profile_fact,
    update_dossier_fact,
    update_osint_fact,
    update_profile_fact,
)

logger = logging.getLogger("ov_black.routers.facts")

router = APIRouter(prefix="/clients", tags=["facts"])


def _raise_for_outcome(outcome: FactOutcome) -> None:
    """Map a non-OK :class:`FactOutcome` to the right HTTP exception."""
    if outcome is FactOutcome.CLIENT_NOT_FOUND:
        raise HTTPException(status_code=404, detail="client_not_found")
    if outcome is FactOutcome.FACT_NOT_FOUND:
        raise HTTPException(status_code=404, detail="fact_not_found")
    if outcome is FactOutcome.INVALID_SOURCE_KIND:
        raise HTTPException(status_code=400, detail="invalid_source_kind")
    raise HTTPException(status_code=500, detail="internal_error")


# ── Dossier facts ────────────────────────────────────────────────────────


@router.post(
    "/{client_id}/dossier/facts",
    status_code=status.HTTP_201_CREATED,
    response_model=DossierFactDetail,
    summary="Add a private fact to a client's Dossier.",
)
async def create_dossier_fact_endpoint(
    client_id: uuid.UUID,
    payload: DossierFactCreate,
    user: AuthenticatedUser = Depends(require_advisor),
    session: AsyncSession = Depends(get_session),
) -> DossierFactDetail:
    result = await create_dossier_fact(
        session,
        advisor_id=_advisor_id(user),
        client_id=client_id,
        payload=payload,
    )
    if result.outcome is not FactOutcome.OK or result.fact is None:
        _raise_for_outcome(result.outcome)
    return DossierFactDetail.model_validate(result.fact, from_attributes=True)


@router.patch(
    "/{client_id}/dossier/facts/{fact_id}",
    response_model=DossierFactDetail,
    summary="Edit a Dossier fact (kind / text).",
)
async def update_dossier_fact_endpoint(
    client_id: uuid.UUID,
    fact_id: uuid.UUID,
    payload: DossierFactUpdate,
    user: AuthenticatedUser = Depends(require_advisor),
    session: AsyncSession = Depends(get_session),
) -> DossierFactDetail:
    result = await update_dossier_fact(
        session,
        advisor_id=_advisor_id(user),
        client_id=client_id,
        fact_id=fact_id,
        payload=payload,
    )
    if result.outcome is not FactOutcome.OK or result.fact is None:
        _raise_for_outcome(result.outcome)
    return DossierFactDetail.model_validate(result.fact, from_attributes=True)


@router.delete(
    "/{client_id}/dossier/facts/{fact_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Soft-redact a Dossier fact.",
)
async def redact_dossier_fact_endpoint(
    client_id: uuid.UUID,
    fact_id: uuid.UUID,
    body: RedactRequest,
    user: AuthenticatedUser = Depends(require_advisor),
    session: AsyncSession = Depends(get_session),
) -> Response:
    result = await redact_dossier_fact(
        session,
        advisor_id=_advisor_id(user),
        client_id=client_id,
        fact_id=fact_id,
        reason=body.reason,
    )
    if result.outcome is not FactOutcome.OK:
        _raise_for_outcome(result.outcome)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── Profile facts ────────────────────────────────────────────────────────


@router.post(
    "/{client_id}/profile/facts",
    status_code=status.HTTP_201_CREATED,
    response_model=ProfileFactDetail,
    summary="Add a Profile fact (traveler self-expression).",
)
async def create_profile_fact_endpoint(
    client_id: uuid.UUID,
    payload: ProfileFactCreate,
    user: AuthenticatedUser = Depends(require_advisor),
    session: AsyncSession = Depends(get_session),
) -> ProfileFactDetail:
    result = await create_profile_fact(
        session,
        advisor_id=_advisor_id(user),
        client_id=client_id,
        payload=payload,
    )
    if result.outcome is not FactOutcome.OK or result.fact is None:
        _raise_for_outcome(result.outcome)
    return ProfileFactDetail.model_validate(result.fact, from_attributes=True)


@router.patch(
    "/{client_id}/profile/facts/{fact_id}",
    response_model=ProfileFactDetail,
    summary="Edit a Profile fact (kind / text).",
)
async def update_profile_fact_endpoint(
    client_id: uuid.UUID,
    fact_id: uuid.UUID,
    payload: ProfileFactUpdate,
    user: AuthenticatedUser = Depends(require_advisor),
    session: AsyncSession = Depends(get_session),
) -> ProfileFactDetail:
    result = await update_profile_fact(
        session,
        advisor_id=_advisor_id(user),
        client_id=client_id,
        fact_id=fact_id,
        payload=payload,
    )
    if result.outcome is not FactOutcome.OK or result.fact is None:
        _raise_for_outcome(result.outcome)
    return ProfileFactDetail.model_validate(result.fact, from_attributes=True)


@router.delete(
    "/{client_id}/profile/facts/{fact_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Soft-redact a Profile fact.",
)
async def redact_profile_fact_endpoint(
    client_id: uuid.UUID,
    fact_id: uuid.UUID,
    body: RedactRequest,
    user: AuthenticatedUser = Depends(require_advisor),
    session: AsyncSession = Depends(get_session),
) -> Response:
    result = await redact_profile_fact(
        session,
        advisor_id=_advisor_id(user),
        client_id=client_id,
        fact_id=fact_id,
        reason=body.reason,
    )
    if result.outcome is not FactOutcome.OK:
        _raise_for_outcome(result.outcome)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── OSINT facts ──────────────────────────────────────────────────────────


@router.post(
    "/{client_id}/osint/facts",
    status_code=status.HTTP_201_CREATED,
    response_model=OsintFactDetail,
    summary="Add an OSINT fact (external research).",
)
async def create_osint_fact_endpoint(
    client_id: uuid.UUID,
    payload: OsintFactCreate,
    user: AuthenticatedUser = Depends(require_advisor),
    session: AsyncSession = Depends(get_session),
) -> OsintFactDetail:
    result = await create_osint_fact(
        session,
        advisor_id=_advisor_id(user),
        client_id=client_id,
        payload=payload,
    )
    if result.outcome is not FactOutcome.OK or result.fact is None:
        _raise_for_outcome(result.outcome)
    return OsintFactDetail.model_validate(result.fact, from_attributes=True)


@router.patch(
    "/{client_id}/osint/facts/{fact_id}",
    response_model=OsintFactDetail,
    summary="Edit an OSINT fact (kind / text).",
)
async def update_osint_fact_endpoint(
    client_id: uuid.UUID,
    fact_id: uuid.UUID,
    payload: OsintFactUpdate,
    user: AuthenticatedUser = Depends(require_advisor),
    session: AsyncSession = Depends(get_session),
) -> OsintFactDetail:
    result = await update_osint_fact(
        session,
        advisor_id=_advisor_id(user),
        client_id=client_id,
        fact_id=fact_id,
        payload=payload,
    )
    if result.outcome is not FactOutcome.OK or result.fact is None:
        _raise_for_outcome(result.outcome)
    return OsintFactDetail.model_validate(result.fact, from_attributes=True)


@router.delete(
    "/{client_id}/osint/facts/{fact_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Soft-redact an OSINT fact.",
)
async def redact_osint_fact_endpoint(
    client_id: uuid.UUID,
    fact_id: uuid.UUID,
    body: RedactRequest,
    user: AuthenticatedUser = Depends(require_advisor),
    session: AsyncSession = Depends(get_session),
) -> Response:
    result = await redact_osint_fact(
        session,
        advisor_id=_advisor_id(user),
        client_id=client_id,
        fact_id=fact_id,
        reason=body.reason,
    )
    if result.outcome is not FactOutcome.OK:
        _raise_for_outcome(result.outcome)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
