# ovb — operator CLI + e2e harness + generated SDK

One core, three faces. `ovb` drives a **live or local** OV Black stack the same way
the UI does — view and mutate itinerary graphs, search inventory, run Analyze/Fill,
and **chat with the agent as a traveler or as staff** — with `--json` on every
command for scripting/agent use.

```
┌─────────────────────────────────────────────────────────────┐
│ ovb.cli         rich-rendered, AWS-style commands  (--json)  │  ← humans + agents
├─────────────────────────────────────────────────────────────┤
│ ovb.scenario / ovb.invariants   state tracking + assertions  │  ← pytest e2e
├─────────────────────────────────────────────────────────────┤
│ ovb.sdk (+ ovb.agent SSE)   typed async client over apps/api │  ← shared core
│ ovb._generated   pydantic models generated from the OpenAPI  │
└─────────────────────────────────────────────────────────────┘
```

The CLI and the pytest e2e suite are both thin clients of `ovb.sdk`, so a
documented manual flow and an automated test are the same scenario expressed two
ways. The agent turn loop lives in `ovb.agent` (not the generated SDK) because
OpenAPI doesn't model the SSE stream — the web makes the same split via
`apps/web/lib/agentStream.ts`.

## Setup

```bash
cd apps/cli
uv sync                     # install deps + the ovb console script
uv run ovb --help
```

The SDK models in `src/ovb/_generated/models.py` are committed (like
`packages/api-client/src/generated`). **After an apps/api schema change**, regenerate:

```bash
./scripts/generate.sh       # in-process app.openapi() → datamodel-codegen (no server/DB/AWS)
```

## Targeting (profiles)

Profiles resolve `built-ins → .cli file → env → command flags`. `local` is the
default; `staging` reads the same env names the verify scripts use.

Auth and other settings live in an **AWS-style `.cli` file** with `[profile NAME]`
sections — so secrets/identity need not be re-exported each call. Discovery:
`$OVB_CONFIG` (authoritative when set) → `<repo>/.cli` → `~/.ovblack/.cli` → `~/.cli`.
It is gitignored (it can hold keys).

```ini
# ~/.ovblack/.cli
[ovb]
default_profile = local

[profile local]
api_url = http://127.0.0.1:8000
supabase_url = http://127.0.0.1:54321
email = you@example.com
role  = advisor

[profile staging]
api_url = https://your-staging-api
service_role_key = <supabase service role key>
jwt = <pre-minted OV_BLACK_STAGING_JWT>   ; used verbatim when set
```

```bash
ovb configure init                          # scaffold a starter ~/.ovblack/.cli
ovb configure show                          # resolved active profile (secrets redacted)
ovb configure path                          # which .cli is in effect
ovb --profile staging ...                   # select a profile
ovb --api-url http://127.0.0.1:8011 ...      # one-off base-URL override
```

Keys per profile: `api_url`, `supabase_url`, `anon_key`, `password`,
`auth_method`, `service_role_key`, `jwt`, `email` (`default_email`), `role`
(`default_role`), `verify_tls`. Environment still wins over the file, and
`--api-url` / `--email` / `--as` flags win over everything.

## Identity — traveler vs staff

"As traveler" vs "as staff" is just which JWT is presented (apps/api derives
actor_kind from `public.profiles.role` — the token is the same shape either way).

```bash
ovb whoami                                  # mint + decode the active identity
ovb auth mint --role traveler --email x@y.com   # prints ONLY the token (composes into env)
export OV_BLACK_STAGING_JWT="$(ovb --profile staging auth mint)"
```

### Auth methods (how the JWT is obtained)

`auth_method` per profile selects the credential source — the API validates the
resulting Supabase JWT identically regardless:

- **`password`** (recommended off-box) — logs a dedicated **service user** in via
  the Supabase password grant using the publishable `anon_key`. **No service-role
  key**; the password lives in the profile/secret and never reaches our backend
  (Supabase verifies the hash). The grant authenticates one user/role, so use a
  second profile (e.g. `staging-traveler`) for the other role.
- **`admin`** — `scripts/mint-jwt.sh` (needs the service-role key; can mint any
  role and syncs `public.profiles`). The local default.
- **`auto`** (default) — `password` when a `password` is set, else `admin`.
- A pre-supplied `jwt` (e.g. `OV_BLACK_STAGING_JWT`) short-circuits both.

```ini
[profile staging]
api_url = https://your-staging-api
supabase_url = https://<project>.supabase.co
auth_method = password
anon_key = <publishable anon key>     ; not secret
email = svc-advisor@your-domain
password = <service user's password>  ; secret — lives here only
role = advisor
```

```bash
ovb --profile staging auth mint --method password   # force the grant explicitly
```

## Commands (AWS-style)

```bash
ovb health                                  # public liveness
ovb clients list                            # advisor's clients
ovb clients create --name "A P" --email ap@x.com
ovb itinerary list
ovb itinerary get <itin-id>                 # renders the graph as a follows-chain
ovb node add <itin-id> --type hotel --title Aman --cost-amount 1200 --cost-currency USD
ovb node from-inventory <itin-id> --source duffel --source-id <id>
ovb inventory search --kind flight --origin LAX --destination HND --departure-date 2026-09-01
ovb analyze start <itin-id> --depth standard --wait     # queue, poll, print findings
ovb fill run <itin-id> --start <iso> --end <iso>
ovb demo-japan --client-id <id>
```

### Chat (the SSE turn loop)

```bash
# interactive, as a traveler
ovb chat repl --client-id <id> --as traveler

# one-shot, as staff (streams the reply live; --json for structured output)
ovb chat open --client-id <id>
ovb chat say --session-id <sid> "What can you help me plan?" --as staff
ovb chat turns --session-id <sid>
```

For a **deterministic** agent locally (no Bedrock/agent process), run the API in
mock-agent mode and point `ovb` at it:

```bash
cd ../api && agent_local_url= bedrock_agentcore_runtime_arn= uv run uvicorn app.main:app --port 8011
ovb --api-url http://127.0.0.1:8011 scenario smoke      # green end-to-end
```

### Agent evals (EVAL-1 — the LIVE agent, scored)

`ovb agent eval` runs declarative scenarios against the **real** agent and
scores each turn on invariants, never wording: which tools fired, which SSE
frames were emitted, what the graph diff was, plus an optional LLM-judge
rubric (`--judge`, Bedrock — skips honestly without creds).

Tool observability comes from the debug-gated `tool_trace` SSE frame
(`{"type":"tool_trace","phase":"call|result","tool":...,"status":...}` —
name + toolUseId + status only, never inputs/outputs). The agent emits it when
`EMIT_TOOL_TRACE=1` (the mprocs pane and `scripts/restart-agent.sh` set it;
browsers drop the unknown frame type, so real UIs never see it). `ovb chat`
also renders the fires inline (`⚙ search_inventory`) and reports
`tools_called` under `--json`.

```bash
ovb agent eval scenarios.json --client-id <id> --itinerary-id <id> [--judge]
```

A scenario file is one object, a list, or `{"scenarios": [...]}`:

```json
{
  "name": "analyze-conversational",
  "audience": "advisor",
  "turns": [{
    "say": "Please check this plan for conflicts and tell me what you find.",
    "expect_tools": ["run_analysis"],
    "forbid_tools": ["propose_card"],
    "expect_frames": [],
    "expect_prose": [],
    "expect_diff": {"no_change": true},
    "rubric": "Reports concrete, plan-specific findings — not generic advice."
  }]
}
```

`expect_tools` checks as a set-subset (`"tools_ordered": true` for an ordered
subsequence); `expect_diff` supports `min_nodes_added` / `min_nodes_removed` /
`statuses_to` / `no_change`. The same runner backs the pytest lane
(`tests/e2e/test_agent_eval_e2e.py`, marker `live_agent` — run those isolated,
they contend for the one local agent).

## Tests

```bash
uv run pytest -m "not e2e"        # offline: SSE parsing, config/auth, SDK (respx), invariants
uv run pytest -m e2e              # live: targets the active profile, self-skips if unreachable
uv run pytest                     # both
```

E2E asserts on **invariants** (a turn persisted, the graph stays sound, findings
exist) — not on the agent's exact wording — so it passes against the local mock
or real Bedrock. Lint/type with `uv run ruff check . && uv run mypy`.

## Scope notes

`ovb.invariants` includes honest stubs (`status_actor_gate_holds`,
`money_gate_reconciles`) that raise `NotImplementedError` — they light up when
M004 (status gates) and M005 (invoices/bookings) land, rather than passing falsely.
