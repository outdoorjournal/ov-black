# apps/agent — Bedrock AgentCore runtime

This is the concierge agent that lives behind the ARN in the
`bedrock-agentcore-runtime-arn` secret. [apps/api](../api) invokes it
via `bedrock-agentcore:InvokeAgentRuntime`; this workspace is the code
that runs on the other side.

## Three modes

One agent, one system prompt assembled per turn. Mode is derived by
FastAPI at turn-start and passed in the payload:

- **onboarding** — first-touch conversation grounded on the seeded
  Voodoo Doll. No itinerary writes yet.
- **planning** — client or advisor stitching together a draft itinerary.
  Agent proposes cards, orders days, accepts adjustments.
- **qa** — the itinerary is approved; answer questions factually
  across all of the client's trips.

See [src/agent/prompts/](src/agent/prompts/) for the rubrics and
[src/agent/tools/](src/agent/tools/) for the tool bundles per mode.

## Local development

```bash
cd apps/agent
uv sync                              # install deps
uv run python -m agent               # serve on :8080
```

The runtime speaks the AgentCore HTTP contract: `POST /invocations`
with a JSON body, streams `data: ...\n\n` SSE frames back. Tools call
back to FastAPI at `BACKEND_BASE_URL` (default `http://localhost:8000`)
using the Supabase JWT carried on the payload.

Before the API can reach this runtime locally you need to pick a
client and point the FastAPI service at it — set `AGENT_LOCAL_URL` in
`apps/api/.env` and the runtime dispatch flips from the mock to a
local HTTP shim (see [apps/api/app/agent/bedrock.py](../api/app/agent/bedrock.py)).

## Deployment

```bash
cd apps/agent
uv run agentcore configure -e src/agent/app.py    # first run only
uv run agentcore launch                           # build + push + create
```

`agentcore launch` builds an ARM64 container via CodeBuild, pushes to
ECR, creates/updates the runtime, and prints the new ARN. Write the
ARN to Secrets Manager:

```bash
aws secretsmanager put-secret-value \
  --secret-id ov-black-staging/bedrock-agentcore-runtime-arn \
  --secret-string <ARN>
```

CDK-managed provisioning is deferred — `@aws-cdk/aws-bedrock-agentcore-alpha`
has a known `IdleRuntimeSessionTimeout=60s` default bug (aws-cdk#36376).

## Configuration

Env vars read by [src/agent/config.py](src/agent/config.py):

| Var | Default | Purpose |
|---|---|---|
| `AWS_REGION` | `us-west-2` | Bedrock region |
| `BEDROCK_MODEL_ID` | `anthropic.claude-sonnet-4-5-20250929-v1:0` | Foundation model |
| `BACKEND_BASE_URL` | `http://localhost:8000` | FastAPI base URL |
| `BACKEND_TIMEOUT_SECONDS` | `15.0` | Per-tool HTTP timeout |
| `MAX_PRIOR_TURNS` | `20` | Cap on replayed history |
| `LOG_LEVEL` | `INFO` | |

## Payload contract

FastAPI sends a JSON object validated by
[src/agent/schemas.py::TurnPayload](src/agent/schemas.py):

```json
{
  "system": "<voice preamble + Voodoo Doll context>",
  "input_text": "<current user message>",
  "prior_turns": [{"role": "user|assistant", "content": "..."}, ...],
  "mode": "onboarding | planning | qa",
  "auth_bearer": "<Supabase JWT>",
  "actor_kind": "user | advisor",
  "client_id": "<uuid>",
  "itinerary_id": "<uuid or null>"
}
```

## Frame contract (runtime → browser, via FastAPI passthrough)

```
data: {"type": "delta", "text": "..."}
data: {"type": "card_proposed", "node": {...}}
data: {"type": "draft_assembled", "edges_created": 7}
data: {"type": "node_updated", "node": {...}}
data: {"type": "error", "reason": "invalid_payload" | "internal_error"}
data: {"type": "done"}
```

`delta` is streamed tokens, one per chunk. The three write-frames are
emitted by [src/agent/translate.py](src/agent/translate.py) when it
observes a tool-result for `propose_card`, `assemble_draft`, or
`update_node_status`. The browser dispatches on `type`.

## Tests

```bash
uv run pytest -q
```

## References

- Plan: [/Users/cmyers/.claude/plans/humble-questing-goose.md](../../../.claude/plans/humble-questing-goose.md)
- Original M001 S04 research: [.gsd/milestones/M001/slices/S04/S04-RESEARCH.md](../../.gsd/milestones/M001/slices/S04/S04-RESEARCH.md)
- Client-side dispatch: [apps/api/app/services/agent.py](../api/app/services/agent.py)
- Voice reference: [apps/api/app/agent/prompt.py](../api/app/agent/prompt.py)
