# Runbook — M001/F2 real staging deploy

> Operator runbook for standing up **apps/api + apps/web** in staging on ECS Fargate (one shared,
> HTTPS ALB) and proving the M001 loop runs against real Supabase + real Bedrock. Companion to [mvp-plan.md](../mvp-plan.md)
> §3 (slice **F2**) and the CDK in [infra/cdk](../../infra/cdk/). Everything here is operator
> work that needs AWS creds + the live Supabase project — it cannot run in hermetic CI.
>
> **F2 acceptance (from the plan):** `scripts/verify-s01.sh` + `scripts/verify-f2.sh` pass against
> `STAGING_API_URL`, and a magic-link email actually arrives.

---

## 0. What this gets you

ONE public ALB fronting **both** apps on ECS Fargate, over HTTPS with a real domain:
- **web** — `https://black.dev.outdoorvoyage.com` (Next.js standalone container, :3000)
- **api** — `https://api.black.dev.outdoorvoyage.com` (apps/api, :8000)

Host-based routing on the shared ALB sends the api host → the API target group and everything else →
web; HTTP:80 redirects to 443. The API reaches the live Supabase Postgres, verifies real Supabase
JWTs, and can invoke the Bedrock AgentCore runtime. TLS is an ACM cert (`black.dev.outdoorvoyage.com`
+ `*.black.dev.outdoorvoyage.com`), DNS-validated in the `dev.outdoorvoyage.com` Route53 zone (same
account).

**Environment is real and already populated** in [`infra/cdk/cdk.json`](../../infra/cdk/cdk.json):
account `437988666846`, region `us-east-2`, VPC `vpc-0b7a7ad7cc2e34da2`. You should not need to
touch VPC/subnet context.

### Gaps this slice closed (so the deploy is actually functional)

The CDK shipped the M001 *shape* but never the env a running container needs. F2 wired these — read
them so you know what the secrets below feed:

| Was broken | Symptom it caused | Fix (this slice) |
|---|---|---|
| No `DATABASE_URL` injected | App fell back to `localhost:54322`; every DB request 500s | New `ov-black/staging/database-url` secret → `DATABASE_URL` |
| Supabase JWT shipped as a JSON blob (`SUPABASE_JWT`), app reads flat vars | JWKS/issuer empty → every authed route 401s | `supabase-jwt` secret now `{url,issuer,jwks_url}`, each extracted into `SUPABASE_URL` / `SUPABASE_JWT_ISSUER` / `SUPABASE_JWKS_URL` |
| `Settings.env` never set (`OV_BLACK_ENV` is not read by the app) | Stayed `local`; agent could fall back to the mock runtime | Injects `ENV=staging` (`prod`→`production`) |
| Default `INVENTORY_PROVIDERS_ENABLED=ov,mock` | **Boot crash** — mock eagerly loads `tests/fixtures/…`, excluded from the image | Pins to `ov,google_places,duffel` (real providers only; keys wired below) |
| No `AWS_REGION` for the agentcore client | boto3 targeted the wrong region | Injects `AWS_REGION=us-west-2` (the `agentcoreRegion` context) |

---

## 1. Prerequisites

```bash
# Refresh the SSO session (it expires; this is the #1 reason a deploy step fails).
aws sso login --profile tov-sso
aws sts get-caller-identity --profile tov-sso        # expect account 437988666846

export AWS_PROFILE=tov-sso
export AWS_REGION=us-east-2                            # the ECS/ALB region
```

Tools: Docker (with buildx for cross-arch), Node ≥24 + pnpm ≥9, the `supabase` CLI, `psql`/`curl`.
You also need the **Supabase project credentials** (service-role key, DB password, project ref) and,
for the agent, the ability to provision a Bedrock AgentCore runtime.

One-time per account (skip if already done): `pnpm -C infra/cdk cdk bootstrap aws://437988666846/us-east-2`.

**Hosted zone id (required before deploy).** `cdk.json` ships `hostedZoneId` as a placeholder
(`REPLACE_WITH_DEV_OUTDOORVOYAGE_ZONE_ID`). Fill it with the real id of the `dev.outdoorvoyage.com`
zone or the cert + A records won't deploy:

```bash
aws route53 list-hosted-zones --profile tov-sso \
  --query "HostedZones[?Name=='dev.outdoorvoyage.com.'].Id" --output text   # → /hostedzone/Z…
```

Put the bare `Z…` id into `ov-black:envs.staging.hostedZoneId` in `cdk.json`.

---

## 2. Deploy the secrets stack (placeholders first)

The stack seeds every secret with a `REPLACE_ME` (or empty-JSON) sentinel so it deploys from a clean
checkout; you populate real values in step 3.

```bash
pnpm -C infra/cdk cdk deploy OvBlackSecrets-staging
```

This creates six secrets under `ov-black/staging/`:

| Secret name | Consumed as | Holds |
|---|---|---|
| `supabase-service-role` | `SUPABASE_SERVICE_ROLE_KEY` | Supabase service-role key (admin API / invite redemption) |
| `supabase-jwt` | `SUPABASE_URL` + `SUPABASE_JWT_ISSUER` + `SUPABASE_JWKS_URL` | JSON `{url,issuer,jwks_url}` |
| `database-url` | `DATABASE_URL` | async SQLAlchemy DSN |
| `agent-token-signing-secret` | `AGENT_TOKEN_SIGNING_SECRET` | HS256 key for per-session agent tokens |
| `bedrock-agentcore-runtime-arn` | `BEDROCK_AGENTCORE_RUNTIME_ARN` | AgentCore runtime ARN (set in step 5) |
| `inventory-provider-keys` | `GOOGLE_PLACES_API_KEY` + `DUFFEL_API_KEY` | JSON `{google_places, duffel}` — one secret for all vendor keys (per-secret cost) |

---

## 3. Populate the secret values

> Never paste secrets into shell history on a shared box; prefer `--secret-string file://…` and shred
> the file. None of these values may be logged (R017 redaction discipline).

```bash
SM="aws secretsmanager put-secret-value --profile tov-sso --region us-east-2"

# 3a. Supabase service-role key (Dashboard → Project Settings → API → service_role).
$SM --secret-id ov-black/staging/supabase-service-role --secret-string 'eyJ...service_role...'

# 3b. Supabase URL + JWT issuer + JWKS (replace <ref> with your project ref).
$SM --secret-id ov-black/staging/supabase-jwt --secret-string '{
  "url":      "https://<ref>.supabase.co",
  "issuer":   "https://<ref>.supabase.co/auth/v1",
  "jwks_url": "https://<ref>.supabase.co/auth/v1/.well-known/jwks.json"
}'

# 3c. Database DSN. Use the SESSION pooler (port 5432) and rewrite the scheme to
#     postgresql+asyncpg://. Do NOT use the transaction pooler (6543) — apps/api's
#     asyncpg engine uses prepared statements, which the transaction pooler breaks
#     (db.py passes no statement_cache override). Password from Dashboard → Database.
$SM --secret-id ov-black/staging/database-url --secret-string \
  'postgresql+asyncpg://postgres.<ref>:<DB_PASSWORD>@aws-0-us-east-2.pooler.supabase.com:5432/postgres'

# 3d. Per-session agent-token signing key (32+ bytes of randomness).
$SM --secret-id ov-black/staging/agent-token-signing-secret --secret-string "$(openssl rand -base64 48)"

# 3e. Inventory-provider vendor keys — ONE JSON secret holding every vendor key
#     (Secrets Manager bills per-secret, so they're folded together). Set both fields
#     in a single put (a put REPLACES the whole value — include every field each time):
#       - google_places: Google Cloud console → APIs & Services → Credentials. Places
#         API New + Maps must be enabled; restrict the key by HTTP referrer / IP.
#       - duffel: Duffel dashboard → Settings → Access tokens. Staging may use a
#         duffel_test_ token (simulated airlines); prod wants a duffel_live_ token.
#     Any field left empty → that provider degrades to [] with a no_credentials warning
#     (no boot crash). Add ratehawk's key id + key here as new JSON fields when it lands.
$SM --secret-id ov-black/staging/inventory-provider-keys --secret-string '{
  "google_places": "AIza...",
  "duffel":        "duffel_test_..."
}'

# 3f. bedrock-agentcore-runtime-arn is set in step 5, after the runtime exists.
```

---

## 4. Apply database migrations

The remote Supabase project is provisioned but the schema must be at migration **0015**. From repo root:

```bash
supabase link --project-ref <ref>      # one-time
supabase db push                        # applies supabase/migrations/0001 … 0015
```

Sanity: `psql "<direct-connection-string>" -c '\dt public.*'` should show `nodes`, `itineraries`,
`card_templates`, `parties`, `dossiers`, etc.

---

## 5. Provision the Bedrock AgentCore runtime, then record its ARN

The agent runtime (the **apps/agent** workspace) is provisioned **out of band** — CDK does not manage
it yet (see the note in [secrets-stack.ts](../../infra/cdk/lib/secrets-stack.ts)). AgentCore Runtime
requires an **arm64** image; [`apps/agent/Dockerfile`](../../apps/agent/Dockerfile) already targets
`linux/arm64`. Use the starter toolkit's `agentcore launch` (it drives CodeBuild with the right arch)
or the console.

Provision it in the region you set as `agentcoreRegion` (default **us-west-2** — AgentCore
early-availability + apps/api's default; it does **not** have to match the ECS region). Then:

```bash
# ARN shape: arn:aws:bedrock-agentcore:us-west-2:437988666846:runtime/<runtime-id>
aws secretsmanager put-secret-value --profile tov-sso --region us-east-2 \
  --secret-id ov-black/staging/bedrock-agentcore-runtime-arn \
  --secret-string 'arn:aws:bedrock-agentcore:us-west-2:437988666846:runtime/<runtime-id>'
```

If you provision in a region other than us-west-2, set `ov-black:envs.staging.agentcoreRegion` in
`cdk.json` to match and redeploy the API stack (it injects `AWS_REGION` for the boto3 client).

---

## 6. Configure Supabase SMTP — Resend (so magic-link emails actually deliver)

All auth email — the **welcome** link sent when an advisor adds a client (`POST /clients` →
Supabase `inviteUserByEmail`) and the **sign-in** magic link (`POST /auth/login`) — is sent by
**Supabase Auth**, not apps/api. There are no SMTP settings in the API and apps/api never needs a
Resend key. Supabase's built-in mailer is rate-limited and only sends to project members, so staging
relays through **Resend**:

- Resend → verify the sending domain (e.g. `outdoorvoyage.black`) and create an API key.
- Supabase Dashboard → **Authentication → Emails → SMTP Settings** → enable custom SMTP:
  host `smtp.resend.com`, port `465`, user `resend`, password = the Resend API key, sender on the
  verified domain. *(Already configured on the staging project.)*
- Under **URL Configuration** set the Site URL and add the web origin
  `https://black.dev.outdoorvoyage.com` (and `https://black.dev.outdoorvoyage.com/auth/callback`) to
  **Redirect URLs** — the `redirect_to` must be allow-listed or the link 400s.

There is **no invite code** — adding a client provisions their auth row and emails a code-free
welcome sign-in link; everything after is the email magic-link flow. The same Resend SMTP block is
mirrored (commented) in `supabase/config.toml` so the local/CLI stack can opt into real mail with
`RESEND_API_KEY`; left commented, local dev uses inbucket. Templates:
`supabase/templates/invite.html` (welcome) and `magic_link.html` (returning sign-in).

`WEB_ORIGIN` is wired automatically: the CDK derives it from `webHost`
(`https://black.dev.outdoorvoyage.com`) and injects it into apps/api for CORS + magic-link redirects.

---

## 7. Build, push, and deploy apps/api + apps/web

> **Build for `linux/amd64`.** The Fargate tasks set no `runtimePlatform`, so they default to amd64.
> On an Apple-Silicon machine a plain `docker build` produces arm64 and the task dies with an
> exec-format error. Neither Dockerfile pins the platform — pass it on the CLI.

```bash
ACCOUNT=437988666846; REGION=us-east-2
ECR="$ACCOUNT.dkr.ecr.$REGION.amazonaws.com"
TAG="sha-$(git rev-parse --short HEAD)"

aws ecr get-login-password --profile tov-sso --region $REGION \
  | docker login --username AWS --password-stdin "$ECR"

# apps/api — build context is apps/api.
docker buildx build --platform linux/amd64 \
  -t "$ECR/ov-black-api-staging:$TAG" --push apps/api

# apps/web — build context is the REPO ROOT (pnpm workspace + @ov-black/api-client),
# -f the web Dockerfile. NO build args: public config (Supabase URL + anon key,
# API base URL, Mapbox token) is read at RUNTIME from the web task env (OVB_*),
# wired in cdk.json -> api-stack.ts. One image works for every environment.
docker buildx build --platform linux/amd64 -f apps/web/Dockerfile \
  -t "$ECR/ov-black-web-staging:$TAG" --push .

# One deploy stands up the cert + DNS + both services. Omit a tag and that service
# ships the hello-world placeholder.
pnpm -C infra/cdk cdk deploy OvBlackApi-staging -c imageTag="$TAG" -c webImageTag="$TAG"
```

**First deploy pauses on ACM validation** (a few minutes) while CloudFormation writes the DNS
validation records into the `dev.outdoorvoyage.com` zone — automatic (same-account zone), not a
manual step. `cdk deploy` then prints the `WebUrl` / `ApiUrl` outputs.

---

## 8. Verify

```bash
export STAGING_API_URL="https://api.black.dev.outdoorvoyage.com"

# Quick smoke: both hosts answer 200 on /health, and http redirects to https.
curl -fsS "$STAGING_API_URL/health" && echo
curl -fsS https://black.dev.outdoorvoyage.com/health && echo
curl -sS -o /dev/null -w 'http→ %{http_code}\n' http://black.dev.outdoorvoyage.com/   # expect 301

# Mint a real Supabase JWT (needs the live project's service-role key).
export OV_BLACK_STAGING_JWT="$(SUPABASE_URL=https://<ref>.supabase.co \
  SUPABASE_SERVICE_ROLE_KEY=<service_role_key> \
  scripts/mint-jwt.sh --email you@example.com --role client)"

scripts/verify-s01.sh      # deploy bar: /health 200, authed 401/200, web build, cdk synth
scripts/verify-f2.sh       # data-plane: openapi, /health, authed 401, authed 200, GET /me/itineraries 200
```

`verify-f2.sh` is the F2-specific proof. Without `OV_BLACK_STAGING_JWT` it **skips** checks 4–5 (and
warns the deploy is unproven). The two checks that matter most:

- **Check 4** (`/health/authed` 200) → Supabase JWKS/issuer reached the app (the JSON-blob gap).
- **Check 5** (`/me/itineraries` 200 + body) → the app resolved a client row and queried Postgres
  (the `DATABASE_URL` gap). A `500` here is the signature of a bad/missing DSN.

**Manual (not automated):** trigger a real invite, confirm the magic-link **email arrives**, click it,
and land in `/chat/[client_id]`. That closes the second half of F2 acceptance.

If the service won't stabilize, the circuit breaker rolls back; read the cause in CloudWatch
`/ecs/ov-black-api-staging` (a boot crash from a bad secret shows here as a Python traceback).

---

## 9. Still owed after F2 (tracked, not done here)

- **Remaining vendor providers** — `google_places` + `duffel` are wired (keys in the single
  `inventory-provider-keys` secret + enabled in `INVENTORY_PROVIDERS_ENABLED`, see §2/§3). Ratehawk is
  still owed: extend the flag to `ov,google_places,duffel,ratehawk`, add `ratehawk_key_id` +
  `ratehawk_api_key` as new JSON fields in that **same** secret (no new secret), and extract each into
  its env var in `api-stack.ts` (`EcsSecret.fromSecretsManager(secret, 'ratehawk_key_id')`). Out of
  scope for M001/F2.
- **CDK-managed AgentCore** — runtime provisioning is still console/CLI out-of-band (S05 deferral).
- **F3 founder craft-feel UAT** — run the M001 craft checks against this deploy (separate slice).

---

## 10. Rollback / teardown

```bash
# Roll back to a previous good image (no rebuild):
pnpm -C infra/cdk cdk deploy OvBlackApi-staging -c imageTag=<previous-good-tag>

# Tear down the API (staging only — RETAIN protects prod). Secrets stack is kept
# so populated values survive; delete it explicitly only when decommissioning.
pnpm -C infra/cdk cdk destroy OvBlackApi-staging
```
