"""E2E fixtures — target a live API by profile, self-skip when unreachable.

Mirrors the verify-sNN.sh posture: local by default, staging when the env names
those scripts use are present. Every fixture degrades to ``pytest.skip`` rather
than failing, so the offline suite (``-m "not e2e"``) and a credential-less CI
both stay green.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

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


@pytest.fixture
async def harness(profile: Profile, _reachable: None) -> AsyncIterator[Harness]:
    async with Harness(profile=profile) as h:
        yield h


@pytest.fixture
async def advisor(harness: Harness) -> Ovb:
    try:
        ovb = harness.advisor()
    except AuthError as exc:
        pytest.skip(f"cannot mint advisor JWT (Supabase down?): {exc}")
    try:
        await ovb.health_authed()
    except ApiError as exc:
        pytest.skip(f"advisor JWT not accepted by API: {exc}")
    return ovb
