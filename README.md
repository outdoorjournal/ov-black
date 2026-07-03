# Running ov-black locally

End-to-end local setup: local Supabase (Postgres + Auth + Studio), FastAPI, and
the Next.js advisor/client UI. AgentCore is mocked — no AWS creds needed.

## Prerequisites

- Node ≥ 24, pnpm ≥ 9
- Python 3.13 via pyenv, `uv` for Python deps (never use `pip` directly)
- Supabase CLI ≥ 2.x, Docker Desktop running

## One-time install

```bash
pnpm install
cd apps/api && uv sync --frozen && cd -
```

## 1. Start local Supabase

```bash
supabase start
```

This boots Postgres (`:54322`), Kong/API (`:54321`), Studio (`:54323`), Mailpit
(`:54324`) and auto-applies every migration under [supabase/migrations/](supabase/migrations/).

Capture credentials for the env files:

```bash
supabase status -o env
```

Keys you'll need:
- `API_URL` → `http://127.0.0.1:54321`
- `ANON_KEY` → goes to web
- `SERVICE_ROLE_KEY` → goes to api

## 2. Env files

### `apps/api/.env`

```ini
env=local
log_level=DEBUG

database_url=postgresql+asyncpg://postgres:postgres@127.0.0.1:54322/postgres

supabase_url=http://127.0.0.1:54321
supabase_jwt_issuer=http://127.0.0.1:54321/auth/v1
supabase_jwks_url=http://127.0.0.1:54321/auth/v1/.well-known/jwks.json
supabase_service_role_key=<SERVICE_ROLE_KEY from `supabase status -o env`>

web_origin=http://localhost:3000

inventory_providers_enabled=mock

aws_region=us-west-2
bedrock_agentcore_runtime_arn=
bedrock_agentcore_memory_id=
```

Leaving `bedrock_agentcore_runtime_arn` blank makes [app/main.py](apps/api/app/main.py)
wire `MockAgentRuntimeClient` on startup, so the agent turn loop works without
AWS credentials.

#### Document vault (optional) — real local uploads via Supabase Storage

By default `vault_bucket_name` is blank, so [app/main.py](apps/api/app/main.py)
wires `MockVaultStorage`: presigned URLs point at a dead `mock-s3.local` host and
a browser PUT no-ops. To exercise **real** upload/download locally — bytes stored,
download works — back the vault with local Supabase's S3-compatible endpoint
instead of AWS. Add to `apps/api/.env` (values from `supabase status`):

```ini
vault_bucket_name=vault
s3_endpoint_url=http://127.0.0.1:54321/storage/v1/s3
s3_region=local
s3_access_key_id=<S3_PROTOCOL_ACCESS_KEY_ID>
s3_secret_access_key=<S3_PROTOCOL_ACCESS_KEY_SECRET>
```

The private `vault` bucket is declared in [supabase/config.toml](supabase/config.toml)
and created on `supabase start`. When `s3_endpoint_url` is set, the presigner
([app/vault/storage.py](apps/api/app/vault/storage.py)) signs with path-style
addressing + those keys instead of the AWS credential chain; staging/prod leave
it blank and use a real S3 bucket. The test suite always forces `MockVaultStorage`,
so this never affects pytest.

### `apps/web/.env.local`

```ini
NEXT_PUBLIC_SUPABASE_URL=http://127.0.0.1:54321
NEXT_PUBLIC_SUPABASE_ANON_KEY=<ANON_KEY from `supabase status -o env`>
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

## 3. Start the API

```bash
cd apps/api
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Smoke test: `curl http://127.0.0.1:8000/health` → `{"status":"ok"}`.

OpenAPI docs: http://127.0.0.1:8000/docs

## 4. Start the web app

```bash
pnpm -C apps/web dev
```

→ http://localhost:3000

## 5. (Optional) Regenerate the TS API client

Any time you change a FastAPI route or Pydantic model:

```bash
pnpm -C packages/api-client generate
pnpm -C packages/api-client build
```

The `generate` script boots `apps/api` itself, fetches `/openapi.json`, emits
`src/generated/`, and tears down — do **not** start the API separately first.

## First-time login

Local Supabase ships without SMTP wired up, so the normal "redeem invite →
email arrives → click link" loop dead-ends. Use the bootstrap script instead:

```bash
scripts/bootstrap-login.sh --email you@example.com --role advisor
```

Flags: `--email` (default: `git config user.email`), `--role advisor|client`
(default: `advisor`). It creates (or reuses) the auth user, ensures a
`public.profiles` row with the requested role, mints a magic-link token via
the Supabase admin API, and prints a pre-built `/auth/callback?token_hash=…`
URL you click to land on the web app logged in.

The script only touches local services — it will refuse to run if `supabase
start` is not up. See the header of [scripts/bootstrap-login.sh](scripts/bootstrap-login.sh)
for env overrides.

## Known local-dev caveat: auth

[apps/api/app/auth.py](apps/api/app/auth.py) validates Supabase JWTs as
**RS256** via JWKS. Supabase CLI stacks currently sign local JWTs with
**ES256**, so any authenticated route will return `401 unknown_signing_key`.

Unauthenticated surfaces still work end-to-end locally:
- `/health`, `/docs`, `/openapi.json`, `/redoc`
- `POST /auth/redeem-invite` (the only public auth entrypoint)

To exercise authenticated routes locally you have a few options:
- relax the algorithm list in `verify_token` to include `ES256` and teach
  `JWKSCache` to handle EC keys, for local dev only;
- mint an RS256 token against a fixture JWKS and point `supabase_jwks_url` at
  it (the pattern tests already use);
- run against the remote provisioned Supabase project instead of local.

## Handy URLs

| Service            | URL                                  |
|--------------------|--------------------------------------|
| Web                | http://localhost:3000                |
| API                | http://127.0.0.1:8000                |
| API docs           | http://127.0.0.1:8000/docs           |
| Supabase Studio    | http://127.0.0.1:54323               |
| Supabase API       | http://127.0.0.1:54321               |
| Mailpit (emails)   | http://127.0.0.1:54324               |
| Postgres           | postgresql://postgres:postgres@127.0.0.1:54322/postgres |

## Shutdown

```bash
# Ctrl-C the uvicorn and next dev terminals, then:
supabase stop
```
