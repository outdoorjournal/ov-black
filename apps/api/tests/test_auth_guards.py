"""Coverage for ``app.auth_guards.require_advisor`` (S03 T03).

The guard is a FastAPI dependency that sits on top of the JWT middleware:
by the time it runs, ``user.sub`` has already been validated. Its only
job is to (1) parse ``user.sub`` as a UUID, (2) look up
``public.profiles``, and (3) 403 ``advisor_only`` unless the row is
present AND its role is ``advisor``.

We test the guard as a coroutine with a FakeSession — the JWT path is
covered end-to-end by ``test_auth.py`` and is not re-exercised here.
The ``make_token`` / RSA-keypair fixtures are used to mint a realistic
``AuthenticatedUser`` principal, so the sub values flowing through the
guard look exactly like a production token.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import pytest
from fastapi import HTTPException

from app.auth import AuthenticatedUser, verify_token
from app.auth_guards import require_advisor
from app.models import Profile, UserRole

if TYPE_CHECKING:
    from collections.abc import Callable


# --- Fakes ------------------------------------------------------------------


@dataclass
class _ExecResult:
    value: Any = None

    def scalar_one_or_none(self) -> Any:
        return self.value


@dataclass
class FakeSession:
    """Minimal async-session stand-in for the advisor guard.

    Holds a map of profiles keyed by ``uuid.UUID``. ``execute`` pulls the
    bound ``id`` parameter out of the compiled statement and returns the
    matching row (or ``None`` — the guard treats both as 403).
    """

    profiles: dict[uuid.UUID, Profile] = field(default_factory=dict)

    async def execute(self, stmt: Any) -> _ExecResult:
        params = stmt.compile().params
        # SQLAlchemy binds the WHERE value under a generated name like
        # "id_1"; scan the bound values for a UUID that matches a seeded
        # profile. No match → return None (profile_not_found path).
        for value in params.values():
            if isinstance(value, uuid.UUID) and value in self.profiles:
                return _ExecResult(self.profiles[value])
        return _ExecResult(None)


def _profile(sub: uuid.UUID, role: UserRole) -> Profile:
    return Profile(id=sub, role=role)


def _principal_for(sub: str) -> AuthenticatedUser:
    return AuthenticatedUser(
        sub=sub,
        email="someone@example.com",
        role="authenticated",
        claims={"sub": sub},
    )


# --- Guard behaviour --------------------------------------------------------


@pytest.mark.asyncio
async def test_require_advisor_returns_user_unchanged_for_advisor_profile() -> (
    None
):
    advisor_sub = uuid.uuid4()
    session = FakeSession(
        profiles={advisor_sub: _profile(advisor_sub, UserRole.advisor)}
    )
    principal = _principal_for(str(advisor_sub))

    result = await require_advisor(user=principal, session=session)  # type: ignore[arg-type]

    assert result is principal
    assert result.sub == str(advisor_sub)


@pytest.mark.asyncio
async def test_require_advisor_rejects_client_role_with_403(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client_sub = uuid.uuid4()
    session = FakeSession(
        profiles={client_sub: _profile(client_sub, UserRole.client)}
    )
    principal = _principal_for(str(client_sub))

    with caplog.at_level(logging.INFO, logger="ov_black.auth_guards"):
        with pytest.raises(HTTPException) as exc_info:
            await require_advisor(user=principal, session=session)  # type: ignore[arg-type]

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "advisor_only"
    # The rejection reason + sub_hint must be logged, the full sub must not.
    record = next(
        r for r in caplog.records if r.name == "ov_black.auth_guards"
    )
    assert record.message == "auth_guards.require_advisor.reject"
    assert getattr(record, "reason") == "not_advisor"
    assert getattr(record, "sub_hint") == str(client_sub)[:8]
    assert str(client_sub) not in record.getMessage()


@pytest.mark.asyncio
async def test_require_advisor_rejects_missing_profile_with_403(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # The session has no matching profile — a freshly-auth'd user who
    # never had a profiles row inserted. Indistinguishable from a client
    # by design (same 403 body).
    session = FakeSession(profiles={})
    stranger_sub = uuid.uuid4()
    principal = _principal_for(str(stranger_sub))

    with caplog.at_level(logging.INFO, logger="ov_black.auth_guards"):
        with pytest.raises(HTTPException) as exc_info:
            await require_advisor(user=principal, session=session)  # type: ignore[arg-type]

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "advisor_only"
    record = next(
        r for r in caplog.records if r.name == "ov_black.auth_guards"
    )
    assert getattr(record, "reason") == "profile_not_found"
    assert getattr(record, "sub_hint") == str(stranger_sub)[:8]


@pytest.mark.asyncio
async def test_require_advisor_rejects_malformed_sub_with_403(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # A sub that is not a UUID (e.g. an opaque user id from a misconfigured
    # tenant) must not crash the guard — it 403s with a distinct reason.
    session = FakeSession()
    principal = _principal_for("not-a-uuid-123456")

    with caplog.at_level(logging.INFO, logger="ov_black.auth_guards"):
        with pytest.raises(HTTPException) as exc_info:
            await require_advisor(user=principal, session=session)  # type: ignore[arg-type]

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "advisor_only"
    record = next(
        r for r in caplog.records if r.name == "ov_black.auth_guards"
    )
    assert getattr(record, "reason") == "malformed_sub"
    assert getattr(record, "sub_hint") == "not-a-uu"


# --- JWT fixture integration check ------------------------------------------


def test_jwt_fixture_mints_a_principal_whose_sub_flows_into_the_guard(
    make_token: "Callable[..., str]",
) -> None:
    """Sanity check: the RSA fixture's tokens carry the sub we expect.

    The guard consumes ``user.sub`` verbatim. If the conftest fixture ever
    drifts from the claim shape the guard expects, this test catches it at
    the boundary instead of inside the four behaviour tests above.
    """
    advisor_sub = str(uuid.uuid4())
    token = make_token(sub=advisor_sub, email="advisor@example.com")

    principal = verify_token(token)

    assert principal.sub == advisor_sub
    assert principal.email == "advisor@example.com"
