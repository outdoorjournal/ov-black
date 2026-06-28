# Web e2e (Playwright)

Browser end-to-end tests for `apps/web`, runnable against **local** or **staging**
with the same suite. Separate from Vitest (which stays unit/component, under
`apps/web/tests/`). These tests are **not** part of `pnpm test` / CI — they need a
running stack and are invoked explicitly.

## Layout

```
e2e/
  auth.setup.ts                 # logs an advisor in once, saves the session
  support/auth.ts               # mints the magic-link callback URL (local OR staging)
  public/login-page.spec.ts     # unauthenticated landing page
  authenticated/                # specs that reuse the saved advisor session
    command-center.spec.ts
  .auth/advisor.json            # captured cookies (gitignored, written by setup)
```

Three Playwright projects: `setup` (logs in) → `authenticated` (depends on it),
and `public` (no auth, independent).

## How login works here

The web app is magic-link only and stores the session in HTTP-only cookies, so
we can't inject a token into localStorage. Instead `auth.setup.ts` mints a fresh
**single-use** magic-link token and drives the real `/auth/callback` route —
exactly the loop a user completes by clicking their email link. The resulting
cookies are saved to `.auth/advisor.json` and reused by authenticated specs.

- **Local** — `support/auth.ts` shells out to `scripts/bootstrap-login.sh`, which
  creates the auth user + `profiles` row and prints the callback URL. The
  service-role key is read from `apps/api/.env`, same as every other local helper.
- **Staging/remote** — it calls the Supabase admin API directly with
  `SUPABASE_SERVICE_ROLE_KEY`. The advisor user must already be provisioned
  (see `scripts/provision-staging-users.sh`).

## Running

### Local

Prereqs: `supabase start` is up, the API is on `:8000`, and `apps/api/.env` has
the service-role key. The Next dev server is started (or reused) automatically.

```bash
pnpm -C apps/web test:e2e                 # all projects, headless
pnpm -C apps/web test:e2e:public          # just the public landing page (no Supabase needed)
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
E2E_ADVISOR_EMAIL=<provisioned advisor email> \
  pnpm -C apps/web test:e2e
```

No web server is started for remote targets — the suite drives the deployed app.

## Config knobs

| Env var                     | Default                     | Purpose                                        |
| --------------------------- | --------------------------- | ---------------------------------------------- |
| `PLAYWRIGHT_BASE_URL`       | `http://localhost:3000`     | Target web app. Non-local disables the dev server. |
| `SUPABASE_URL`              | `http://127.0.0.1:54321`    | Which Supabase backs the target.               |
| `SUPABASE_SERVICE_ROLE_KEY` | (read from `apps/api/.env`) | Required for remote token minting.             |
| `E2E_ADVISOR_EMAIL`         | `e2e-advisor@ovblack.test`  | The advisor identity to log in as.             |
