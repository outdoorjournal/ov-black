# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## AWS

Use AWS_PROFILE=tov-sso when working with AWS resources. The `tov-sso` profile is configured for SSO access to the Outdoor Voyage AWS account. If you don't have it set up, ask for access and instructions.

## What this is

Outdoor Voyage: Black — an invitation-only, AI-native concierge platform for ultra-wealthy travelers. The product is deliberately anti-instant: it uses "strategic friction" (dripped progress updates) to feel bespoke, and treats the itinerary graph as the single source of truth across client-facing, advisor-facing, and AI surfaces. See [doc/prd.md](doc/prd.md) for product requirements.

## Monorepo layout

pnpm workspaces + Turbo, pinned to Node ≥24 / pnpm ≥9 / Python 3.13. Workspaces live under `apps/*`, `packages/*`, `infra/*`.

- [apps/api](apps/api/) — FastAPI backend (Python 3.13, uv, SQLAlchemy async + asyncpg, Supabase JWT middleware, Bedrock AgentCore). Runs on ECS Fargate behind an ALB in staging/prod.
- [apps/web](apps/web/) — Next.js 15 + React 19 + Tailwind 3 advisor/client UI (App Router, typed routes, Vitest + jsdom). Components under [apps/web/app/_components](apps/web/app/_components/) and [apps/web/components/ui](apps/web/components/ui/) (shadcn-style).
- [packages/api-client](packages/api-client/) — TypeScript client **generated** from the FastAPI OpenAPI schema via `@hey-api/openapi-ts`. `src/index.ts` wraps the generated SDK into discriminated `{ ok: true | false, detail }` results; `src/generated/` is machine-emitted and should never be hand-edited.
- [infra/cdk](infra/cdk/) — AWS CDK v2 (TypeScript) stacks: `SecretsStack` (Supabase + AgentCore ARN secrets) and `ApiStack` (ECR, ECS Fargate, ALB, CloudWatch). Imports an existing VPC by ID/subnet attributes so `cdk synth` is hermetic — no AWS creds needed in CI.
- [supabase/](supabase/) — migrations only (no app code). The **remote Supabase project is already provisioned**; `supabase/config.toml` is for local dev. Ask before creating new Supabase projects.

## Commands

### Root (turbo orchestrates all JS/TS workspaces)

```bash
pnpm install                # install all workspaces
pnpm build                  # turbo run build across workspaces
pnpm lint                   # turbo run lint
pnpm test                   # turbo run test (web vitest, others noop)
pnpm typecheck              # turbo run typecheck
```

### apps/api (FastAPI, uv-managed — never use pip directly)

```bash
cd apps/api
uv sync --frozen            # install deps from uv.lock
uv run uvicorn app.main:app --reload   # local dev on :8000
uv run pytest -q            # full suite
uv run pytest tests/test_auth.py::test_name -q    # single test
```

Pytest is configured with `asyncio_mode = "auto"` — async tests don't need a decorator.

### apps/web (Next 15 + React 19)

```bash
pnpm -C apps/web dev        # next dev on :3000
pnpm -C apps/web build
pnpm -C apps/web test       # vitest (jsdom); add --run for CI-style non-watch
pnpm -C apps/web test -- tests/agentStream.test.ts   # single file
pnpm -C apps/web typecheck
```

### packages/api-client (regenerate after API schema changes)

```bash
pnpm -C packages/api-client generate   # boots apps/api, curls /openapi.json, emits src/generated/, tears down
pnpm -C packages/api-client build      # tsc → dist/
```

`scripts/generate.sh` owns the whole FastAPI boot/fetch/shutdown lifecycle — do not start the API separately first.

### infra/cdk

```bash
pnpm -C infra/cdk synth     # hermetic, no AWS creds needed
pnpm -C infra/cdk cdk deploy OvBlackApi-staging -c imageTag=<sha>   # needs creds
```

### Slice verification

`scripts/verify-sNN.sh` are per-slice smoke scripts run against a deployed staging environment. They expect `STAGING_API_URL` (and optionally `OV_BLACK_STAGING_JWT`) in env and exit non-zero on failure.

## Architecture notes

### Auth perimeter (R017)

- Every non-whitelisted route on the FastAPI app goes through `JWTAuthMiddleware` ([apps/api/app/auth.py](apps/api/app/auth.py)) which validates RS256 Supabase JWTs against the JWKS endpoint and attaches the principal to `request.state.user`.
- Public paths: `/health`, OpenAPI surfaces, and `POST /auth/redeem-invite` (the only public auth entrypoint — it has no token yet).
- Route handlers read the principal via `require_user` / `AuthenticatedUser`. Advisor-only routes further gate with helpers in [apps/api/app/auth_guards.py](apps/api/app/auth_guards.py).

### Itinerary graph is the spine

The domain is a graph of nodes (destinations, hotels, experiences, etc.) and edges, persisted in Postgres and exposed through `/itinerary/*` routes. Nodes carry `status` (proposed → approved/discarded) and `actor_kind` (agent vs. advisor vs. client). Every surface — client mood board, advisor Command Center, agent SSE stream — reads and mutates this same graph. See migrations [0002_itinerary_graph.sql](supabase/migrations/0002_itinerary_graph.sql) onward.

### Agent turn loop (S04)

- `POST /sessions` opens an AgentCore session (idempotent per client_id) and returns `{session_id, agentcore_session_id, itinerary_id}`.
- `POST /sessions/{id}/turn` streams SSE frames: `delta` (token deltas), `card` (inventory proposal persisted as a graph node before forwarding), `done`, `error`.
- Frontend consumes SSE with a DIY reader in [apps/web/lib/agentStream.ts](apps/web/lib/agentStream.ts); no streaming types are generated into `packages/api-client`.
- Locally, if `BEDROCK_AGENTCORE_RUNTIME_ARN` is unset, `app.main:lifespan` wires a `MockAgentRuntimeClient` so `uvicorn --reload` and pytest run without AWS creds.

### Generated client contract

`packages/api-client` is the **only** way `apps/web` talks to `apps/api`. After any FastAPI schema change (new route, new Pydantic field), re-run `pnpm -C packages/api-client generate` and commit the regenerated `src/generated/`. The top-level `src/index.ts` wrappers collapse `{data, error, response}` into discriminated unions — keep new endpoints following that pattern.

### Inventory providers

[apps/api/app/inventory/](apps/api/app/inventory/) has a provider registry populated at startup from `INVENTORY_PROVIDERS_ENABLED` (comma-separated, defaults `ov,mock`). The `OVProvider` hits the public Outdoor Voyage API; `MockProvider` returns fixture data from `tests/fixtures/mock_inventory.json`. Unknown names are logged and skipped — typos don't crash boot.

### Secrets flow

Never hardcode secrets. In staging/prod they live in Secrets Manager (`SecretsStack`) and are injected into the ECS task by `ApiStack` (`EcsSecret.fromSecretsManager`). Locally, `apps/api/app/config.py` reads from env / `.env`. The service role key is marked `repr=False` in `Settings` — don't log it.

### TS config posture

Root `tsconfig.base.json` enables `strict`, `noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`, `verbatimModuleSyntax`, `noPropertyAccessFromIndexSignature`. Code must be written to satisfy these — don't relax them per-package.

## CI (.github/workflows/ci.yml)

Three required jobs: `workspaces` (turbo lint/typecheck/build/test), `api-pytest` (uv-managed pytest in `apps/api`), `cdk-synth`. A `deploy-staging` job runs only on pushes to `main`, gated by the `staging` GitHub Environment's manual reviewer approval — the deploy step itself is a placeholder until a later milestone.

## GSD workflow

This repo is driven by the `gsd-workflow` MCP server (configured in [.mcp.json](.mcp.json)) which persists state under [.gsd/](.gsd/). `.gsd/PROJECT.md`, `.gsd/STATE.md`, `.gsd/REQUIREMENTS.md`, `.gsd/DECISIONS.md` are the canonical sources for milestone/slice/requirement/decision history — consult them before starting work that spans slices. Slice verification scripts (`scripts/verify-sNN.sh`) pair with slice completion.

## Tooling preferences

- Python: `pyenv` for Python versions, `uv` for deps. Never invoke `pip` directly.
- Frontend deps: prefer latest; Tailwind is currently v3 but v4 upgrade is on the table.
