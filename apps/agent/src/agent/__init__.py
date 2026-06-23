"""Outdoor Voyage: Black — Bedrock AgentCore runtime.

This package is the agent that lives behind the ARN in
``bedrock-agentcore-runtime-arn`` and is invoked by the FastAPI backend
in [apps/api](../../api) via ``bedrock-agentcore:InvokeAgentRuntime``.

Three modes, one Strands ``Agent`` per turn:

- **onboarding** — first-touch conversation grounded on the seeded
  Dossier. No itinerary writes yet.
- **planning** — client + advisor stitching an itinerary. Tools write
  through FastAPI; tool results translate to SSE frames the UI renders.
- **qa** — the itinerary is approved; answer questions factually against
  the graph across all of the client's trips.

See [app.py](./app.py) for the entrypoint and [modes.py](./modes.py) for
the per-turn Strands ``Agent`` factory.
"""

__all__ = ["app"]
