"""Unit tests for the S08 T05 ``assemble_draft`` event branch in ``stream_turn``.

The branch parses the event's ``day_plan``, promotes the actor to AGENT, and
calls :func:`app.services.itineraries.assemble_initial_draft`. The outbound
SSE frame carries ``edges_created: int`` so the advisor surface can reflect
assembly progress without an extra fetch.

These tests reuse the offline fake session + factory machinery from
``test_agent_service.py`` via the package-level fixtures so they stay
network-free and deterministic.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest

from app.agent.bedrock import MockAgentRuntimeClient
from app.config import Settings
from app.models import AgentSession, Itinerary
from app.services import itineraries as itineraries_service
from app.services.agent import ActorContext, stream_turn

# Re-use the FakeFactory / fixtures from the agent-service test module. The
# ``pytest_plugins`` declaration loads that module as a plugin so its
# ``factory`` / ``advisor_actor`` / ``agent_session`` / ``settings`` fixtures
# resolve here; a bare import would bring the class in but not the fixtures.
from tests.test_agent_service import FakeFactory  # noqa: F401 — fixture dep

pytest_plugins = ("tests.test_agent_service",)


async def _collect(stream: AsyncIterator[bytes]) -> list[bytes]:
    out: list[bytes] = []
    async for chunk in stream:
        out.append(chunk)
    return out


def _parse_frames(joined: bytes) -> list[dict[str, Any]]:
    lines = [
        line[len(b"data: "):]
        for line in joined.split(b"\n")
        if line.startswith(b"data: ")
    ]
    return [json.loads(line.decode("utf-8")) for line in lines]


async def test_assemble_draft_roundtrips_with_edges_created(
    factory: "FakeFactory",
    advisor_actor: ActorContext,
    agent_session: AgentSession,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A runtime ``assemble_draft`` event forwards with ``edges_created``.

    The service's ``assemble_initial_draft`` composite is monkeypatched so
    this test can assert the stream_turn branch parses the day_plan,
    promotes the actor to AGENT, and surfaces the edge count from the
    service result onto the forwarded frame. Persistence is tested
    separately in test_itinerary_approval_race.py.
    """
    # Pre-seed an itinerary for this client so the branch skips the
    # ensure-one helper and lands straight in assemble_initial_draft.
    existing = Itinerary(
        client_id=agent_session.client_id,
        title="pre-existing",
    )
    existing.id = uuid.uuid4()
    factory.itineraries.append(existing)

    node_a = uuid.uuid4()
    node_b = uuid.uuid4()

    captured: dict[str, Any] = {}

    async def _fake_assemble(
        session: Any,
        actor: Any,
        *,
        itinerary_id: uuid.UUID,
        day_plan: list[Any],
    ) -> itineraries_service.GraphView:
        captured["actor_kind"] = actor.kind
        captured["itinerary_id"] = itinerary_id
        captured["day_plan"] = day_plan
        return itineraries_service.GraphView(
            itinerary=existing,
            nodes=[],
            edges=[
                itineraries_service.EdgeOut(
                    id=uuid.uuid4(),
                    itinerary_id=itinerary_id,
                    from_node_id=node_a,
                    to_node_id=node_b,
                    type=itineraries_service.EdgeType.follows,
                    metadata={},
                )
            ],
        )

    monkeypatch.setattr(
        "app.services.agent.itineraries_service.assemble_initial_draft",
        _fake_assemble,
    )

    assemble_event = {
        "type": "assemble_draft",
        "day_plan": [
            {
                "day_index": 0,
                "node_ids_in_order": [str(node_a), str(node_b)],
            }
        ],
    }
    runtime = MockAgentRuntimeClient(
        [
            {"type": "delta", "text": "Here's day one."},
            assemble_event,
            {"type": "done"},
        ]
    )

    frames = await _collect(
        stream_turn(
            factory,  # type: ignore[arg-type]
            runtime,
            actor=advisor_actor,
            session_id=agent_session.id,
            content="Assemble it.",
            settings=settings,
        )
    )
    joined = b"".join(frames)
    parsed = _parse_frames(joined)
    assembles = [f for f in parsed if f.get("type") == "assemble_draft"]
    assert len(assembles) == 1
    forwarded = assembles[0]
    assert forwarded["edges_created"] == 1
    assert forwarded["day_plan"] == [
        {
            "day_index": 0,
            "node_ids_in_order": [str(node_a), str(node_b)],
        }
    ]

    # The service call went through with an AGENT actor and a DaySlot-typed
    # day_plan (uuid.UUID entries, not strings).
    assert captured["actor_kind"] is itineraries_service.ActorKind.AGENT
    assert captured["itinerary_id"] == existing.id
    assert captured["day_plan"] == [
        {
            "day_index": 0,
            "node_ids_in_order": [node_a, node_b],
        }
    ]


async def test_assemble_draft_failure_forwards_zero_edges(
    factory: "FakeFactory",
    advisor_actor: ActorContext,
    agent_session: AgentSession,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An ItineraryError result collapses to ``edges_created: 0`` + info log."""
    existing = Itinerary(
        client_id=agent_session.client_id,
        title="pre-existing",
    )
    existing.id = uuid.uuid4()
    factory.itineraries.append(existing)

    async def _failing_assemble(*args: Any, **kwargs: Any) -> itineraries_service.ItineraryError:
        return itineraries_service.ItineraryError(
            outcome=itineraries_service.ItineraryOutcome.VALIDATION_ERROR,
            detail="node_not_in_itinerary",
        )

    monkeypatch.setattr(
        "app.services.agent.itineraries_service.assemble_initial_draft",
        _failing_assemble,
    )

    assemble_event = {
        "type": "assemble_draft",
        "day_plan": [
            {
                "day_index": 0,
                "node_ids_in_order": [str(uuid.uuid4())],
            }
        ],
    }
    runtime = MockAgentRuntimeClient(
        [assemble_event, {"type": "done"}],
    )

    caplog.set_level(logging.INFO, logger="ov_black.agent.service")
    frames = await _collect(
        stream_turn(
            factory,  # type: ignore[arg-type]
            runtime,
            actor=advisor_actor,
            session_id=agent_session.id,
            content="Try it.",
            settings=settings,
        )
    )
    joined = b"".join(frames)
    parsed = _parse_frames(joined)
    assembles = [f for f in parsed if f.get("type") == "assemble_draft"]
    assert len(assembles) == 1
    assert assembles[0]["edges_created"] == 0

    failed = [
        r for r in caplog.records
        if r.getMessage() == "agent.assemble_draft.failed"
    ]
    assert len(failed) == 1
    assert getattr(failed[0], "reason", None) == "validation_error"


async def test_assemble_draft_malformed_payload_short_circuits(
    factory: "FakeFactory",
    advisor_actor: ActorContext,
    agent_session: AgentSession,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A malformed day_plan forwards edges_created=0 without calling the service."""
    call_count = {"n": 0}

    async def _should_not_fire(*args: Any, **kwargs: Any) -> Any:
        call_count["n"] += 1
        raise AssertionError("assemble_initial_draft should not be called")

    monkeypatch.setattr(
        "app.services.agent.itineraries_service.assemble_initial_draft",
        _should_not_fire,
    )

    bad_event = {
        "type": "assemble_draft",
        "day_plan": [
            {
                "day_index": 0,
                "node_ids_in_order": ["not-a-uuid"],
            }
        ],
    }
    runtime = MockAgentRuntimeClient([bad_event, {"type": "done"}])

    caplog.set_level(logging.INFO, logger="ov_black.agent.service")
    frames = await _collect(
        stream_turn(
            factory,  # type: ignore[arg-type]
            runtime,
            actor=advisor_actor,
            session_id=agent_session.id,
            content="Nope.",
            settings=settings,
        )
    )
    joined = b"".join(frames)
    parsed = _parse_frames(joined)
    assembles = [f for f in parsed if f.get("type") == "assemble_draft"]
    assert len(assembles) == 1
    assert assembles[0]["edges_created"] == 0
    assert call_count["n"] == 0

    malformed = [
        r for r in caplog.records
        if r.getMessage() == "agent.assemble_draft.malformed"
    ]
    assert len(malformed) == 1
