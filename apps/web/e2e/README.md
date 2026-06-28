# Web e2e (Playwright)

Browser end-to-end tests for `apps/web`, runnable against **local** or **staging**
with the same suite. Separate from Vitest (which stays unit/component, under
`apps/web/tests/`). These tests are **not** part of `pnpm test` / CI — they need a
running stack and are invoked explicitly.

## Layout

```
e2e/
  advisor.setup.ts              # logs an advisor in, saves the session
  traveler.setup.ts             # logs a traveler (client) in, saves the session
  support/auth.ts               # mints the magic-link callback URLs (local OR staging)
  public/login-page.spec.ts     # unauthenticated landing page
  advisor/command-center.spec.ts   # advisor session → /command-center
  traveler/basecamp.spec.ts        # traveler session → /basecamp
  .auth/{advisor,traveler}.json    # captured cookies (gitignored)
```

Projects: `setup:advisor` → `advisor`, `setup:traveler` → `traveler` (and
`setup:traveler` runs after `setup:advisor`, since it reuses the advisor to
create the traveler's linked client), plus `public` (no auth, independent).

## How login works here

The web app is magic-link only and stores the session in HTTP-only cookies, so
we can't inject a token into localStorage. Each setup mints a fresh
**single-use** magic-link token and drives the real `/auth/callback` route —
exactly the loop a user completes by clicking their email link. The resulting
cookies are saved under `.auth/` and reused by the persona specs.

- **Advisor** lands on `/command-center`. Local → `scripts/bootstrap-login.sh`
  provisions the auth user + `profiles` row; remote → mints via the Supabase
  admin API (advisor must be pre-provisioned).
- **Traveler** lands on `/basecamp`, which only resolves once their auth user is
  linked to a `clients` row (matched by email via `GET /me/client`). Locally the
  setup provisions that link first: it mints an advisor token, `POST /clients`
  with the traveler's email (which also creates the invited auth user — this must
  happen before the user exists, mirroring `scripts/provision-local-users.sh`),
  confirms the user, then mints the link. Remote → assumes the traveler is
  pre-provisioned.

## Running

### Local

Prereqs: `supabase start` is up, the API is on `:8000`, and `apps/api/.env` has
the service-role key. The Next dev server is started (or reused) automatically —
keeping `pnpm -C apps/web dev` running yourself is fastest and most reliable.

```bash
pnpm -C apps/web test:e2e                 # all projects, headless
pnpm -C apps/web test:e2e:public          # just the public landing page (no Supabase needed)
pnpm -C apps/web test:e2e -- --project=advisor    # one persona
pnpm -C apps/web test:e2e -- --project=traveler
pnpm -C apps/web test:e2e:ui              # interactive UI mode
pnpm -C apps/web test:e2e -- --headed     # watch it drive a real browser
pnpm -C apps/web test:e2e:report          # open the last HTML report
```

The `submitting an email` test in `public/` also needs the API on `:8000`.

### Staging (or any deployed env)

```bash
PLAYWRIGHT_BASE_URL=https://<staging-web-host> \
SUPABASE_URL=https://<project>.supabase.co \
SUPABASE_SERVICE_ROLE_KEY=<staging service role key> \
E2E_ADVISOR_EMAIL=<provisioned advisor> \
E2E_TRAVELER_EMAIL=<provisioned, client-linked traveler> \
  pnpm -C apps/web test:e2e
```

No web server is started for remote targets — the suite drives the deployed app.

## Config knobs

| Env var                     | Default                     | Purpose                                            |
| --------------------------- | --------------------------- | -------------------------------------------------- |
| `PLAYWRIGHT_BASE_URL`       | `http://localhost:3000`     | Target web app. Non-local disables the dev server. |
| `SUPABASE_URL`              | `http://127.0.0.1:54321`    | Which Supabase backs the target.                   |
| `SUPABASE_SERVICE_ROLE_KEY` | (read from `apps/api/.env`) | Required for remote token minting.                 |
| `E2E_API_BASE_URL`          | `http://localhost:8000`     | API used to provision the traveler's linked client.|
| `E2E_ADVISOR_EMAIL`         | `e2e-advisor@example.com`   | Advisor identity. (`example.com` passes the API's `EmailStr`.) |
| `E2E_TRAVELER_EMAIL`        | `e2e-traveler@example.com`  | Traveler identity.                                 |
