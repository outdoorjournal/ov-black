"""Thin LLM-facing layer for the Bedrock AgentCore turn loop.

Public surface:
- ``AgentRuntimeClient`` Protocol — seam injected by the service layer.
- ``Boto3AgentRuntimeClient`` — real implementation wrapping boto3.
- ``MockAgentRuntimeClient`` — scripted test double.
- ``AgentRuntimeError`` — domain exception for upstream failure.
- ``build_system_prompt`` — voice preamble + disclosure rules + traveler context.
- ``assemble_traveler_context`` — render Dossier + Profile + OSINT into a
  three-section context block. The returned string MUST NEVER be logged.
"""

from app.agent.bedrock import (
    AgentRuntimeClient,
    AgentRuntimeError,
    Boto3AgentRuntimeClient,
    MockAgentRuntimeClient,
)
from app.agent.prompt import build_system_prompt
from app.agent.traveler_context import assemble_traveler_context, format_trip_brief

__all__ = [
    "AgentRuntimeClient",
    "AgentRuntimeError",
    "Boto3AgentRuntimeClient",
    "MockAgentRuntimeClient",
    "assemble_traveler_context",
    "build_system_prompt",
    "format_trip_brief",
]
