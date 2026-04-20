"""Thin LLM-facing layer for the Bedrock AgentCore turn loop (S04).

Public surface:
- ``AgentRuntimeClient`` Protocol — seam injected by the service layer.
- ``Boto3AgentRuntimeClient`` — real implementation wrapping boto3.
- ``MockAgentRuntimeClient`` — scripted test double.
- ``AgentRuntimeError`` — domain exception for upstream failure.
- ``build_system_prompt`` — pure function that wraps the R004 rubric around
  an assembled Voodoo Doll context block.
- ``assemble_context`` — pure function that renders a VoodooDoll row as a
  context block. The returned string MUST NEVER be logged at INFO/WARN.
"""

from app.agent.bedrock import (
    AgentRuntimeClient,
    AgentRuntimeError,
    Boto3AgentRuntimeClient,
    MockAgentRuntimeClient,
)
from app.agent.prompt import build_system_prompt
from app.agent.voodoo_doll_context import assemble_context

__all__ = [
    "AgentRuntimeClient",
    "AgentRuntimeError",
    "Boto3AgentRuntimeClient",
    "MockAgentRuntimeClient",
    "assemble_context",
    "build_system_prompt",
]
