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
uv run ruff check .         # lint
uv run ruff format .        # autoformat (omit to just check: --check)
uv run mypy                 # strict type-check (app/ only; tests excluded)
```

Pytest is configured with `asyncio_mode = "auto"` — async tests don't need a decorator. Ruff (lint + format) and mypy `--strict` are configured under `[tool.ruff]` / `[tool.mypy]` in `pyproject.toml`; both must stay green (CI's `api-lint` job enforces them). Mypy uses the pydantic plugin and type-checks `app/` only.

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

## Driving the live app

Three complementary tools exist for exercising real workflows end-to-end (vs. unit/integration tests). Use them when verifying a feature actually works in the running stack — not as a substitute for pytest/vitest, which remain the fast default. **`ovb` (below) is the default for API-level work** — it wraps the JWT minting + every route in one typed CLI.

### The local stack & restarting the agent

`scripts/dev.sh` brings up the whole local stack in [mprocs](mprocs.yaml) — API (`:8000`), the real concierge **agent** (`:8080`, under `AWS_PROFILE=tov-sso`), and web (`:3000`), each in its own pane with `autorestart: true`; Supabase (DB/Auth/Studio/Mailpit) comes up as a preflight. `scripts/dev.sh --mock` swaps the real agent for the in-process canned mock (no agent pane, **no AWS**). The status pane shows every URL + health.

**The agent does not hot-reload.** The API (`uvicorn --reload`) and web (`next dev`) restart themselves on a code change; the agent pane runs `uv run python -m agent` **without `--reload`**, so after you edit anything under [apps/agent](apps/agent/) — a prompt, a tool, the turn loop — the running agent keeps serving the **old** code until it is restarted. **You must restart it to test a change** (and it's also the fix for a wedged turn).

```bash
scripts/restart-agent.sh    # stop the :8080 agent, bring a fresh one up, wait for /ping
```

The script is the reliable, scriptable restart — use it (not a manual kill). It works both ways: under mprocs it stops the agent and lets `autorestart` relaunch it with the pane's env; standalone (no mprocs) it starts a fresh detached process itself. It blocks until `http://localhost:8080/ping` answers `Healthy` (~1–2s), so a follow-up e2e run won't race a half-started agent; it exits non-zero (with the likely cause — usually an expired `aws sso login --profile tov-sso`) if the agent never comes healthy. Interactive alternative when you're sitting in mprocs: focus the `agent` pane and press `r`.

### `ovb` — operator CLI + e2e harness ([apps/cli](apps/cli/))

A uv-managed Python CLI (package `ovb`) that drives a live/local stack the same way the UI does — view/mutate the itinerary graph, search inventory, run Analyze/Fill, and **chat with the agent as a traveler or staff** (the SSE turn loop). It's a thin layer over a generated SDK ([apps/cli/src/ovb/_generated](apps/cli/src/ovb/_generated/), regenerate with `apps/cli/scripts/generate.sh` after an apps/api schema change) that the pytest e2e suite also uses, so a manual flow and a test are the same scenario. Full docs: [apps/cli/README.md](apps/cli/README.md).

```bash
cd apps/cli && uv run ovb --help          # never pip; uv-managed like apps/api
uv run ovb --json clients list            # --json (global) = machine-readable; use it when driving programmatically
uv run ovb itinerary get <id>             # renders the graph like the UI canvas
uv run ovb --profile local-traveler chat repl --client-id <id>   # interactive turns
uv run ovb --profile mock scenario smoke  # AWS-free end-to-end smoke
```

**Profiles** (AWS-style, selected with `--profile`; defined in a gitignored `.cli` file — run `ovb configure list` / `ovb configure show` to see what's actually present):
- **`local`** (default) — admin minting via `scripts/mint-jwt.sh` (reads the service-role key from `apps/api/.env`); identity defaults to git `user.email` as advisor.
- **`local-advisor` / `local-traveler`** — dedicated service users authenticated via the Supabase **password grant** (no service-role key; the traveler is linked to a client so chat-as-traveler works). Created per dev machine — recreate by provisioning two Supabase users with passwords + `auth_method=password` profiles.
- **`mock`** — targets a deterministic mock-agent API on `:8011` (canned reply, **no LLM/AWS**). Start it: from `apps/api`, `agent_local_url= bedrock_agentcore_runtime_arn= uv run uvicorn app.main:app --port 8011`.
- **`staging`** — commented template; fill in once F2 staging is deployed.

**Auth model:** "as traveler" vs "as staff" is just the JWT's Supabase role (the API resolves actor_kind from `public.profiles.role`). `auth_method` picks *how* the JWT is obtained — `password` (anon key + a service user's password, no god key — preferred off-box), `admin` (mint-jwt.sh), or a pre-supplied `jwt`. Secrets live only in the gitignored `.cli`. Real chat turns need an agent backend: `local-*` hit `:8000` (needs the local agent on `:8080` + Bedrock creds), `mock` hits `:8011` (deterministic, AWS-free).

### `scripts/mint-jwt.sh` — Supabase JWT on stdout

Mints a fresh access_token for a given email and prints **only** the token to stdout (logs go to stderr), so it composes into env vars for HTTP/curl-based probes. Reuses the same admin-API conventions as `bootstrap-login.sh`, but goes one hop further (`/auth/v1/verify`) to extract the actual JWT instead of a clickable magic-link URL.

```bash
# local Supabase, advisor JWT for git user.email
export OV_BLACK_STAGING_JWT="$(scripts/mint-jwt.sh)"

# explicit email + role
scripts/mint-jwt.sh --email me@x.com --role client

# staging — needs the staging service role key
SUPABASE_URL=https://<proj>.supabase.co \
  SUPABASE_SERVICE_ROLE_KEY=... \
  scripts/mint-jwt.sh --email me@x.com
```

Use this for direct API checks (`/itinerary/*`, `/sessions`, `/clients/*/facts`, etc.) where you don't need the UI in the loop. Sibling to `scripts/bootstrap-login.sh`, which is still the right tool when you want to log in via a browser locally.

### Playwright MCP — full-browser end-to-end checks

`@playwright/mcp` is wired up in [.mcp.json](.mcp.json) (`PLAYWRIGHT_HEADLESS=1` by default). Once the MCP server is running, browser tools (`browser_navigate / click / fill / select / screenshot / press_key / wait_for`) are available for driving the actual web UI through Supabase login, Command Center, mood board, agent SSE streams, etc.

Use this only for genuine end-to-end verification — screenshots are token-heavy and UI tests are flakier than API tests. Prefer `mint-jwt.sh` + curl when an API-level check would suffice. Do not pair Playwright with mocked auth: log in through the real magic-link flow so the JWT and middleware are exercised end-to-end.

## Architecture notes

### Auth perimeter (R017)

- Every non-whitelisted route on the FastAPI app goes through `JWTAuthMiddleware` ([apps/api/app/auth.py](apps/api/app/auth.py)) which validates RS256 Supabase JWTs against the JWKS endpoint and attaches the principal to `request.state.user`.
- Public paths: `/health`, OpenAPI surfaces, and `POST /auth/redeem-invite` (the only public auth entrypoint — it has no token yet).
- Route handlers read the principal via `require_user` / `AuthenticatedUser`. Advisor-only routes further gate with helpers in [apps/api/app/auth_guards.py](apps/api/app/auth_guards.py).

### Itinerary graph is the spine

The domain is a graph of nodes (destinations, hotels, experiences, etc.) and edges, persisted in Postgres and exposed through `/itinerary/*` routes. Every trip is an **official trunk** (`forked_from_id IS NULL`) plus private working-copy **forks** (D030): content reaches the trunk only via fork reconcile ("publish", advisor-executed — `accept_all` is the fast path), so advisors and travelers both build in forks and a solo traveler's fork *is* their itinerary. Nodes carry `status` (`pending` → `approved` → `booked`/`confirmed`, plus `discarded`; "proposed to the traveler" is positional — a pending node on the trunk) and every mutation records `actor_kind` (agent vs. advisor vs. client). Traveler approval happens per-node on the trunk (or `POST /itinerary/{id}/nodes/approve-all`) and locks the card; the itinerary-level display bucket (`in_studio`/`with_traveler`/`approved`) is derived at read time in [app/services/display_status.py](apps/api/app/services/display_status.py), never stored. A non-advisor content write on a trunk gets 409 `fork_required` (the web store lazy-forks on the working-copy toggle). Every surface — client mood board, advisor Command Center, agent SSE stream — reads and mutates this same graph. See migrations [0002_itinerary_graph.sql](supabase/migrations/0002_itinerary_graph.sql) onward, especially 0043/0044.

### Traveler context tiers (Dossier + Profile + OSINT)

Three semantically distinct stores feed the agent, each with its own disclosure rule:

- **Dossier** ([dossiers](supabase/migrations/0011_dossier_profile_osint.sql) typed core + `dossier_facts`) — private internal knowledge. Two source kinds: `advisor` (manually entered) and `agent_inferred` (recorded by the agent during a turn). Ground reasoning, **never** reveal verbatim or even acknowledge to the traveler.
- **Profile** (`profile_facts`) — what the traveler self-expressed. Source kinds: `traveler_told` (the agent recorded it) or `advisor` (manually attributed). The agent **may** reference these naturally ("you mentioned …").
- **OSINT** (`osint_facts`) — external research (LinkedIn, press, public records). The agent reads but **NEVER** surfaces, paraphrases, or alludes to it.

The agent fetches all three from the backend-only `GET /agent/context` endpoint in [apps/api/app/routers/agent_internal.py](apps/api/app/routers/agent_internal.py), authenticated by an HS256 per-session token minted at `POST /sessions`. The token is stashed only in the AgentCore runtime — never returned to the browser — so the traveler cannot pull Dossier or OSINT directly. Two write tools mirror the two write semantics: `record_profile_fact` (traveler told us) and `record_dossier_inference` (agent inferred privately). Per-fact CRUD for advisors lives at `/clients/{id}/{tier}/facts` and is reviewable in [/command-center/clients/[id]](apps/web/app/command-center/clients/[id]/page.tsx) under the three-tab detail page. The system prompt is assembled by [apps/api/app/agent/traveler_context.py](apps/api/app/agent/traveler_context.py) and labelled with the disclosure rules so the model has them in its working context every turn.

Redaction discipline: net worth + Dossier + OSINT content must NEVER appear in any log record. The sweep test in [apps/api/tests/test_traveler_context.py](apps/api/tests/test_traveler_context.py) walks every caplog record and asserts no sentinel substring leaks; the `agent_token_signing_secret` is `repr=False` in `Settings`. Don't log the agent token, the user JWT, or fact text.

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

Four required jobs: `workspaces` (turbo lint/typecheck/build/test), `api-lint` (ruff check + format-check + mypy strict in `apps/api`), `api-pytest` (uv-managed pytest in `apps/api`), `cdk-synth`. A `deploy-staging` job runs only on pushes to `main`, gated by the `staging` GitHub Environment's manual reviewer approval — the deploy step itself is a placeholder until a later milestone.

## Planning & project docs

Forward-looking scope and plan live in [doc/mvp.md](doc/mvp.md) (the MVP scope contract) and [doc/mvp-plan.md](doc/mvp-plan.md) (the slice-by-slice build plan). Durable history salvaged from the now-retired GSD workflow lives in [doc/decisions.md](doc/decisions.md) (append-only D0xx decision register with rationale), [doc/requirements.md](doc/requirements.md) (R0xx capability/coverage contract), and [doc/knowledge.md](doc/knowledge.md) (non-obvious engineering lessons). Consult these before starting work that spans slices. Slice verification scripts (`scripts/verify-sNN.sh`) pair with slice completion.

## Tooling preferences

- Python: `pyenv` for Python versions, `uv` for deps. Never invoke `pip` directly.
- Frontend deps: prefer latest; Tailwind is currently v3 but v4 upgrade is on the table.
