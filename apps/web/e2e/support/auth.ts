import { execFileSync } from "node:child_process";
import path from "node:path";

// A stable, throwaway identity for the advisor session. Override per-machine
// or for staging with E2E_ADVISOR_EMAIL. Locally the user + profiles row are
// created on demand by bootstrap-login.sh; on staging it must be provisioned
// ahead of time (see scripts/provision-staging-users.sh).
export const E2E_ADVISOR_EMAIL =
  process.env["E2E_ADVISOR_EMAIL"] ?? "e2e-advisor@ovblack.test";

// Where the captured cookie session is written by e2e/auth.setup.ts and read
// by the `authenticated` project. Relative to the apps/web working directory.
export const ADVISOR_STORAGE_STATE = "e2e/.auth/advisor.json";

// Playwright runs with cwd = the config dir (apps/web), so the repo root is
// two levels up. Used to locate scripts/bootstrap-login.sh.
function repoRoot(): string {
  return path.resolve(process.cwd(), "..", "..");
}

function isLocalSupabase(url: string): boolean {
  return url.includes("127.0.0.1") || url.includes("localhost");
}

interface GenerateLinkResponse {
  properties?: { hashed_token?: string };
  hashed_token?: string;
}

// Remote (staging) path: the advisor user already exists, so we just ask the
// Supabase admin API for a fresh magic-link token and build the callback URL.
async function mintHashedTokenViaAdmin(
  supabaseUrl: string,
  serviceRoleKey: string,
  email: string,
): Promise<string> {
  const resp = await fetch(`${supabaseUrl}/auth/v1/admin/generate_link`, {
    method: "POST",
    headers: {
      apikey: serviceRoleKey,
      Authorization: `Bearer ${serviceRoleKey}`,
      "content-type": "application/json",
    },
    body: JSON.stringify({ type: "magiclink", email }),
  });
  if (!resp.ok) {
    throw new Error(
      `admin/generate_link failed (${resp.status}): ${await resp.text()}`,
    );
  }
  const data = (await resp.json()) as GenerateLinkResponse;
  const hashed = data.properties?.hashed_token ?? data.hashed_token;
  if (!hashed) {
    throw new Error("admin/generate_link returned no hashed_token");
  }
  return hashed;
}

// Local path: reuse the existing bootstrap helper, which idempotently creates
// the auth user, ensures the profiles row, and prints a ready-built callback
// URL. We point its WEB_ORIGIN at our target so the URL host matches baseURL.
function callbackUrlFromBootstrap(baseURL: string, email: string): string {
  const script = path.join(repoRoot(), "scripts", "bootstrap-login.sh");
  const out = execFileSync(script, ["--email", email, "--role", "advisor"], {
    encoding: "utf8",
    env: { ...process.env, WEB_ORIGIN: baseURL },
  });
  const line = out
    .split("\n")
    .map((l) => l.trim())
    .find((l) => l.includes("/auth/callback?token_hash="));
  if (!line) {
    throw new Error(
      `bootstrap-login.sh did not emit a callback URL.\n--- output ---\n${out}`,
    );
  }
  return line;
}

/**
 * Returns a single-use `/auth/callback` URL that, when visited in a browser,
 * verifies a magic-link OTP and establishes an advisor cookie session — the
 * same loop a real user completes by clicking the email link.
 *
 * - Local  (Supabase on 127.0.0.1) → scripts/bootstrap-login.sh provisions the
 *   user/profile and mints the link; the service-role key is read from
 *   apps/api/.env exactly like the other local helpers.
 * - Remote (any other SUPABASE_URL) → mints the link via the admin API using
 *   SUPABASE_SERVICE_ROLE_KEY; the advisor user must already be provisioned.
 */
export async function advisorCallbackUrl(baseURL: string): Promise<string> {
  const supabaseUrl = process.env["SUPABASE_URL"] ?? "http://127.0.0.1:54321";

  if (isLocalSupabase(supabaseUrl)) {
    return callbackUrlFromBootstrap(baseURL, E2E_ADVISOR_EMAIL);
  }

  const serviceRoleKey = process.env["SUPABASE_SERVICE_ROLE_KEY"];
  if (!serviceRoleKey) {
    throw new Error(
      "Targeting a remote Supabase but SUPABASE_SERVICE_ROLE_KEY is unset. " +
        "Export the staging service-role key and ensure the advisor user is provisioned.",
    );
  }
  const hashed = await mintHashedTokenViaAdmin(
    supabaseUrl,
    serviceRoleKey,
    E2E_ADVISOR_EMAIL,
  );
  return `${baseURL}/auth/callback?token_hash=${hashed}&type=magiclink`;
}
