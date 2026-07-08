"""Escalation tool (AGT-4) — post one message onto the human advisor thread.

The agent's only channel to a human: a single ``author_kind='artemis'`` message
on the traveler↔advisor thread for the pinned trip (or the client's basecamp
thread when unpinned). Backend-only route, agent-token authenticated; the
server pins the attribution so the agent can never impersonate a human.
"""

from __future__ import annotations

from strands import tool

from agent.backend import agent_post_json


@tool
async def post_thread_message(content: str) -> dict:
    """Flag something to the human advisor by posting on the advisor thread.

    Use this when a request needs a human: a booking change or cancellation,
    a payment question you can only narrate, a special arrangement outside
    inventory, or any commitment you must not make yourself. Also use it
    proactively when the live plan state shows something material a human
    should act on (a pending merge request going stale, a blocking finding,
    an expiring offer) and the user asks you to escalate it.

    Write ``content`` as a short, specific, self-contained note TO the advisor
    (who/what/when — e.g. "Client asks about adding a private chef evening in
    Kyoto around Sep 26; budget flexible. Please advise options."). The message
    is visible to BOTH the advisor and the traveler on their shared thread, so
    the standard disclosure rules apply: never include Dossier or OSINT
    content. After posting, tell the user you've flagged it to their advisor —
    don't promise a response time.

    Post at most one message per request; don't repeat an escalation the
    thread already carries. Returns the posted message (id + thread_id).
    """
    return await agent_post_json("/agent/thread-message", json={"content": content})
