"""ovb — operator CLI, e2e harness, and generated SDK for the OV Black stack.

Three layers share one core:

- :mod:`ovb.sdk` — a typed async HTTP client over apps/api, returning the
  machine-generated models in :mod:`ovb._generated` (regenerate with
  ``scripts/generate.sh``). The agent turn loop is layered on top in
  :mod:`ovb.agent` because OpenAPI does not model the SSE stream — the web does
  the same split via ``apps/web/lib/agentStream.ts``.
- :mod:`ovb.cli` — a ``rich``-rendered, AWS-style CLI (``--json`` everywhere).
- :mod:`ovb.scenario` / :mod:`ovb.invariants` — stateful scenario tracking and
  reusable assertions for the pytest e2e suite.

The CLI and the e2e tests are both thin clients of this core, so a documented
manual flow and an e2e test are the same scenario expressed two ways.
"""

from ovb.errors import ApiError, AuthError, ConfigError, OvbError

__all__ = ["ApiError", "AuthError", "ConfigError", "OvbError", "__version__"]

__version__ = "0.1.0"
