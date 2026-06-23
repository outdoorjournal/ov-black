"""E2E fixtures — target a live API by profile, self-skip when unreachable.

Mirrors the verify-sNN.sh posture: local by default, staging when the env names
those scripts use are present. Every fixture degrades to ``pytest.skip`` rather
than failing, so the offline suite (``-m "not e2e"``) and a credential-less CI
both stay green.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import flows
import httpx
import pytest

from ovb.config import Profile, resolve_profile
from ovb.errors import ApiError, AuthError, OvbError
from ovb.scenario import Harness
from ovb.sdk import Ovb

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session")
def profile() -> Profile:
    try:
        return resolve_profile(os.environ.get("OVB_PROFILE"))
    except OvbError as exc:  # pragma: no cover - config-dependent
        pytest.skip(f"no resolvable profile: {exc}")


@pytest.fixture(scope="session")
def _reachable(profile: Profile) -> None:
    if not profile.api_url:
        pytest.skip("profile has no api_url")
    try:
        resp = httpx.get(f"{profile.api_url}/health", timeout=2.0, verify=profile.verify_tls)
        resp.raise_for_status()
    except (httpx.HTTPError, OSError) as exc:
        pytest.skip(f"API not reachable at {profile.api_url}: {exc}")


@pytest.fixture(scope="session")
def advisor_profile(profile: Profile) -> Profile:
    """The advisor identity — a dedicated service user (``local-advisor``) using the
    Supabase password grant, NOT the admin-mint default. Resolves ``OVB_ADVISOR_PROFILE``
    or ``{base}-advisor``; falls back to the base profile where no ``*-advisor`` exists
    (so a plain ``local`` / ``staging`` run still works). Provision the local users with
    ``scripts/provision-local-users.sh`` after a ``supabase start``.
    """
    name = os.environ.get("OVB_ADVISOR_PROFILE") or f"{profile.name}-advisor"
    try:
        return resolve_profile(name)
    except OvbError:
        return profile


@pytest.fixture
async def harness(advisor_profile: Profile, _reachable: None) -> AsyncIterator[Harness]:
    async with Harness(profile=advisor_profile) as h:
        yield h


@pytest.fixture
async def advisor(harness: Harness) -> Ovb:
    try:
        ovb = harness.advisor()
    except AuthError as exc:
        pytest.skip(f"cannot authenticate advisor (Supabase down / user not provisioned?): {exc}")
    try:
        await ovb.health_authed()
    except ApiError as exc:
        pytest.skip(f"advisor JWT not accepted by API: {exc}")
    return ovb


# ── traveler identity ────────────────────────────────────────────────────────
# "As traveler" is a second JWT whose role is `client` AND whose account is
# linked to a `clients` row (so `GET /me/client` resolves). That linkage is set
# up per-machine as a dedicated profile (the `local-traveler` service user); we
# resolve it by name so traveler-side flows self-skip where it isn't configured.


@pytest.fixture(scope="session")
def traveler_profile(profile: Profile) -> Profile:
    name = os.environ.get("OVB_TRAVELER_PROFILE") or f"{profile.name}-traveler"
    try:
        return resolve_profile(name)
    except OvbError as exc:
        pytest.skip(f"no traveler profile {name!r} (configure one to run traveler flows): {exc}")


@pytest.fixture
async def traveler(traveler_profile: Profile, _reachable: None) -> AsyncIterator[Ovb]:
    try:
        ovb = Ovb.for_identity(traveler_profile)
    except AuthError as exc:
        pytest.skip(f"cannot authenticate traveler (Supabase down?): {exc}")
    try:
        await ovb.health_authed()
    except ApiError as exc:
        await ovb.aclose()
        pytest.skip(f"traveler JWT not accepted by API: {exc}")
    try:
        yield ovb
    finally:
        await ovb.aclose()


@pytest.fixture
async def linked_traveler_client_id(traveler: Ovb) -> str:
    """The client_id the traveler is linked to — the spine of every traveler flow."""
    try:
        return str((await traveler.my_client()).client_id)
    except ApiError as exc:
        pytest.skip(f"traveler is not linked to a client (GET /me/client → {exc.status}): {exc}")


# ── advisor-owned subjects ───────────────────────────────────────────────────
# A fresh client (unique invite email, so `create` always succeeds) and a built
# itinerary over it — the subjects advisor-side flows (build, analyze, fill,
# cost) operate on without depending on a live agent or a linked traveler.


@pytest.fixture
async def client_under_test(advisor: Ovb) -> tuple[str, str]:
    """(client_id, invite_email) for a freshly created advisor-owned client."""
    try:
        return await flows.ensure_client(advisor, full_name="E2E Subject")
    except ApiError as exc:
        pytest.skip(f"could not create a client under test: {exc}")


@pytest.fixture
async def built_itinerary(advisor: Ovb, client_under_test: tuple[str, str]) -> str:
    """A seeded Japan itinerary (timed, geo-located, multi-day) for the subject client."""
    client_id, _ = client_under_test
    try:
        return await flows.ensure_japan_itinerary(advisor, client_id=client_id)
    except ApiError as exc:
        pytest.skip(f"could not instantiate the Japan itinerary: {exc}")
