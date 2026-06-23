"""Live smoke against a running stack — invariant assertions, agent-backend agnostic.

These assert on invariants that hold whether the turn ran against the local mock
or real Bedrock (a turn was persisted, the graph stays structurally sound) — not
on the agent's exact wording.
"""

from __future__ import annotations

import pytest

from ovb.agent import Conversation
from ovb.invariants import assert_no_violations, graph_integrity
from ovb.scenario import Harness
from ovb.sdk import Ovb

pytestmark = pytest.mark.e2e


async def test_health_public(advisor: Ovb) -> None:
    assert await advisor.health() is not None


async def test_advisor_token_is_accepted(advisor: Ovb) -> None:
    res = await advisor.health_authed()
    assert res is not None


async def test_list_clients_returns_models(advisor: Ovb) -> None:
    clients = await advisor.list_clients()
    assert isinstance(clients, list)


async def test_chat_turn_persists_and_keeps_graph_sound(advisor: Ovb, harness: Harness) -> None:
    clients = await advisor.list_clients()
    if not clients:
        pytest.skip("no clients in this environment; create one to exercise chat")

    client_id = str(clients[0].id)
    convo = await Conversation.open(advisor, client_id=client_id)

    before = len(await advisor.list_turns(convo.session_id))
    result = await convo.say("Hello — what can you help me plan?")
    after = await advisor.list_turns(convo.session_id)

    # Robust across mock vs real Bedrock: a turn was recorded and the stream
    # reached a terminal frame (done or a crafted error). Wording is not asserted.
    assert len(after) >= before + 1
    assert result.done is not None or result.error is not None

    if convo.itinerary_id:
        snap = await harness.snapshot(advisor, convo.itinerary_id)
        assert_no_violations(graph_integrity(snap.graph))
