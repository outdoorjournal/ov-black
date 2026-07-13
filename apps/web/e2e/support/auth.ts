import { execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import {
  closeSync,
  existsSync,
  openSync,
  readFileSync,
  statSync,
  unlinkSync,
  writeFileSync,
} from "node:fs";
import os from "node:os";
import path from "node:path";

// All e2e identities plus-address one real, deliverable mailbox. `POST /clients`
// issues a real Supabase invite whose welcome email is sent through the project's
// SMTP (Resend on staging); an undeliverable recipient domain (example.com / .dev)
// makes GoTrue fail the send with `500 Error sending invite email` (surfaced as
// `502 auth_upstream_unavailable`). Plus-addressing keeps every address unique yet
// lands it in one inbox. Override the base per-machine via $OVB_E2E_EMAIL_BASE.
const E2E_EMAIL_BASE =
  process.env["OVB_E2E_EMAIL_BASE"] ?? "chris@outdoorvoyage.com";

/** `<local>+<tag>@<domain>` from the configured base mailbox. */
export function plusAddress(tag: string): string {
  const [local, domain] = E2E_EMAIL_BASE.split("@");
  return `${local}+${tag}@${domain}`;
}

/** A collision-free, deliverable invite target (fresh client per call). */
export function uniqueEmail(prefix = "e2e"): string {
  return plusAddress(`${prefix}-${randomUUID()}`);
}

// Stable, throwaway identities. Override per-machine / for staging via env.
// Locally the auth users + linkage are created on demand; on staging they must
// be provisioned ahead of time (see scripts/provision-staging-users.sh). The
// fixed +tags keep these addresses stable across runs so captured sessions reuse.
export const E2E_ADVISOR_EMAIL =
  process.env["E2E_ADVISOR_EMAIL"] ?? plusAddress("ovb-e2e-advisor");
export const E2E_TRAVELER_EMAIL =
  process.env["E2E_TRAVELER_EMAIL"] ?? plusAddress("ovb-e2e-traveler");

// Captured cookie sessions, relative to the apps/web working directory.
export const ADVISOR_STORAGE_STATE = "e2e/.auth/advisor.json";
export const TRAVELER_STORAGE_STATE = "e2e/.auth/traveler.json";

// Playwright runs with cwd = the config dir (apps/web), so the repo root is
// two levels up. Used to locate scripts/ and apps/api/.env.
function repoRoot(): string {
  return path.resolve(process.cwd(), "..", "..");
}

function getSupabaseUrl(): string {
  return process.env["SUPABASE_URL"] ?? "http://127.0.0.1:54321";
}

export function getApiBaseUrl(): string {
  return process.env["E2E_API_BASE_URL"] ?? "http://localhost:8000";
}

function isLocalSupabase(url: string): boolean {
  return url.includes("127.0.0.1") || url.includes("localhost");
}

// Service-role key: explicit env wins (required for staging); locally we fall
// back to apps/api/.env, the same source every other local helper reads.
function getServiceRoleKey(supabaseUrl: string): string {
  const fromEnv = process.env["SUPABASE_SERVICE_ROLE_KEY"];
  if (fromEnv) {
    return fromEnv;
  }
  if (isLocalSupabase(supabaseUrl)) {
    const envFile = path.join(repoRoot(), "apps", "api", ".env");
    const prefix = "supabase_service_role_key=";
    const line = readFileSync(envFile, "utf8")
      .split("\n")
      .find((l) => l.startsWith(prefix));
    const key = line?.slice(prefix.length).trim();
    if (key) {
      return key;
    }
  }
  throw new Error(
    "SUPABASE_SERVICE_ROLE_KEY is unset and could not be read from apps/api/.env.",
  );
}

interface GenerateLinkResponse {
  properties?: { hashed_token?: string };
  hashed_token?: string;
}

// Mints a fresh magic-link token via the Supabase admin API. The user must
// already exist (local helpers create it first; staging users are provisioned).
async function mintHashedToken(
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

function callbackUrl(baseURL: string, hashedToken: string): string {
  return `${baseURL}/auth/callback?token_hash=${hashedToken}&type=magiclink`;
}

// ── Advisor ────────────────────────────────────────────────────────────────

// Local path: reuse bootstrap-login.sh, which idempotently creates the auth
// user + profiles row and prints a ready-built callback URL. We point its
// WEB_ORIGIN at our target so the URL host matches baseURL.
function advisorCallbackViaBootstrap(baseURL: string): string {
  const script = path.join(repoRoot(), "scripts", "bootstrap-login.sh");
  const out = execFileSync(
    script,
    ["--email", E2E_ADVISOR_EMAIL, "--role", "advisor"],
    { encoding: "utf8", env: { ...process.env, WEB_ORIGIN: baseURL } },
  );
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
 * A single-use `/auth/callback` URL that establishes an **advisor** session.
 * Local → bootstrap-login.sh provisions the user/profile; remote → mints via
 * the admin API (the advisor user must already be provisioned).
 */
export async function advisorCallbackUrl(baseURL: string): Promise<string> {
  const supabaseUrl = getSupabaseUrl();
  if (isLocalSupabase(supabaseUrl)) {
    return advisorCallbackViaBootstrap(baseURL);
  }
  const key = getServiceRoleKey(supabaseUrl);
  return callbackUrl(baseURL, await mintHashedToken(supabaseUrl, key, E2E_ADVISOR_EMAIL));
}

// ── Traveler (client) ────────────────────────────────────────────────────────

// mint-jwt.sh prints ONLY the advisor's access_token on stdout (logs → stderr),
// ensuring the advisor user/profile exist as a side effect.
//
// Memoized per worker process: minting is a magic-link round-trip, and GoTrue
// rate-limits / invalidates concurrent link generation for the same email. A
// worker that provisions several fresh travelers would otherwise mint the same
// advisor link repeatedly and stomp on itself (and on setup:advisor). One
// advisor access token is good for the whole worker's run.
// Cross-worker cache for the advisor access token. Playwright spreads spec
// FILES across worker processes, and GoTrue invalidates concurrent magic-link
// generation for one email — so if every worker minted its own advisor link at
// startup they'd stomp on each other ("verify did not return access_token").
// The in-process memo alone can't help: each worker is a separate process. So
// we mint exactly once per run and share the token through a tmp file guarded by
// an exclusive lock; late workers wait for the file rather than minting again.
const ADVISOR_TOKEN_CACHE = path.join(
  os.tmpdir(),
  `ovb-e2e-advisor-token-${E2E_ADVISOR_EMAIL.replace(/[^a-z0-9]/gi, "_")}`,
);
const TOKEN_MAX_AGE_MS = 30 * 60 * 1000; // JWTs live ~1h; refresh well inside that.

// Block the current worker without a busy-loop (this code path is sync).
function sleepSync(ms: number): void {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
}

function readFreshCachedToken(): string | null {
  try {
    if (!existsSync(ADVISOR_TOKEN_CACHE)) return null;
    if (Date.now() - statSync(ADVISOR_TOKEN_CACHE).mtimeMs > TOKEN_MAX_AGE_MS) {
      return null;
    }
    const token = readFileSync(ADVISOR_TOKEN_CACHE, "utf8").trim();
    return token || null;
  } catch {
    return null;
  }
}

function runMintJwt(): string {
  const script = path.join(repoRoot(), "scripts", "mint-jwt.sh");
  const token = execFileSync(
    script,
    ["--email", E2E_ADVISOR_EMAIL, "--role", "advisor"],
    { encoding: "utf8" },
  ).trim();
  if (!token) {
    throw new Error("mint-jwt.sh returned no token");
  }
  return token;
}

let cachedAdvisorToken: string | null = null;
export function mintAdvisorAccessToken(): string {
  if (cachedAdvisorToken) {
    return cachedAdvisorToken;
  }

  const cached = readFreshCachedToken();
  if (cached) {
    cachedAdvisorToken = cached;
    return cached;
  }

  // Exactly one worker wins the lock and mints; the others wait for its token.
  const lockPath = `${ADVISOR_TOKEN_CACHE}.lock`;
  let haveLock = false;
  try {
    closeSync(openSync(lockPath, "wx")); // atomic create-or-fail (O_EXCL)
    haveLock = true;
  } catch {
    haveLock = false;
  }

  if (!haveLock) {
    const deadline = Date.now() + 30_000;
    while (Date.now() < deadline) {
      const token = readFreshCachedToken();
      if (token) {
        cachedAdvisorToken = token;
        return token;
      }
      sleepSync(250);
    }
    // The lock holder never delivered (crashed?) — fall through and mint.
  }

  try {
    const token = runMintJwt();
    writeFileSync(ADVISOR_TOKEN_CACHE, token, "utf8");
    cachedAdvisorToken = token;
    return token;
  } finally {
    if (haveLock) {
      try {
        unlinkSync(lockPath);
      } catch {
        /* best-effort unlock */
      }
    }
  }
}

// Ensure a clients row whose email is the traveler's exists, owned by the
// advisor. This is the link key /me/client backfills against. It MUST run
// before the traveler auth user exists: POST /clients issues an invite, which
// Supabase refuses (502) for an already-existing user. The invite itself
// creates the traveler auth user, so order matters (mirrors
// scripts/provision-local-users.sh).
async function ensureTravelerLinkedClient(
  apiBaseUrl: string,
  advisorToken: string,
  email: string,
): Promise<void> {
  const auth = { Authorization: `Bearer ${advisorToken}` };

  // Wave F: GET /clients is a searchable envelope — `?q=` matches email.
  const listResp = await fetch(
    `${apiBaseUrl}/clients?q=${encodeURIComponent(email)}`,
    { headers: auth },
  );
  if (!listResp.ok) {
    throw new Error(`GET /clients failed (${listResp.status})`);
  }
  const { clients } = (await listResp.json()) as {
    clients: Array<{ email?: string | null }>;
  };
  const linked = clients.some(
    (c) => (c.email ?? "").toLowerCase() === email.toLowerCase(),
  );
  if (linked) {
    return;
  }

  const body = {
    full_name: "E2E Linked Traveler",
    email,
    dossier: { typed: { contact_preference: "email", travel_party_notes: "" } },
  };
  const createResp = await fetch(`${apiBaseUrl}/clients`, {
    method: "POST",
    headers: { ...auth, "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!createResp.ok) {
    throw new Error(
      `POST /clients failed (${createResp.status}): ${await createResp.text()}`,
    );
  }
}

// The invited traveler user starts unconfirmed; confirm it so a magic-link OTP
// verifies cleanly.
async function confirmUser(
  supabaseUrl: string,
  serviceRoleKey: string,
  email: string,
): Promise<void> {
  const headers = { apikey: serviceRoleKey, Authorization: `Bearer ${serviceRoleKey}` };
  const listResp = await fetch(
    `${supabaseUrl}/auth/v1/admin/users?filter=${encodeURIComponent(email)}`,
    { headers },
  );
  const data = (await listResp.json()) as {
    users?: Array<{ id: string; email?: string }>;
  };
  const user = (data.users ?? []).find(
    (u) => (u.email ?? "").toLowerCase() === email.toLowerCase(),
  );
  if (!user) {
    return;
  }
  await fetch(`${supabaseUrl}/auth/v1/admin/users/${user.id}`, {
    method: "PUT",
    headers: { ...headers, "content-type": "application/json" },
    body: JSON.stringify({ email_confirm: true }),
  });
}

/**
 * A single-use `/auth/callback` URL that establishes a **traveler/client**
 * session landing on /basecamp. Locally it provisions a client row linked by
 * email (so /me/client resolves) and the confirmed auth user; remotely it
 * assumes the traveler is already provisioned and just mints the link.
 */
export async function travelerCallbackUrl(baseURL: string): Promise<string> {
  const supabaseUrl = getSupabaseUrl();
  const key = getServiceRoleKey(supabaseUrl);

  if (isLocalSupabase(supabaseUrl)) {
    await ensureTravelerLinkedClient(getApiBaseUrl(), mintAdvisorAccessToken(), E2E_TRAVELER_EMAIL);
    await confirmUser(supabaseUrl, key, E2E_TRAVELER_EMAIL);
  }

  return callbackUrl(baseURL, await mintHashedToken(supabaseUrl, key, E2E_TRAVELER_EMAIL));
}

/**
 * Provision a brand-new, throwaway traveler and return a single-use
 * `/auth/callback` URL that logs *them* in (plus their email, for API-level
 * assertions). A unique email each call, so a spec that MUTATES onboarding
 * state — sends a turn, dismisses the opener — never collides with the shared
 * `traveler` persona or with a parallel spec under `fullyParallel`.
 *
 * Local-only: it provisions the linked client + confirmed auth user on demand.
 * We don't create throwaway users against a deployed Supabase, so this throws
 * off-box (the onboarding specs run against the local stack).
 */
export async function freshTravelerCallbackUrl(
  baseURL: string,
): Promise<{ email: string; callbackUrl: string }> {
  const supabaseUrl = getSupabaseUrl();
  if (!isLocalSupabase(supabaseUrl)) {
    throw new Error(
      "freshTravelerCallbackUrl is local-only — it provisions throwaway users, " +
        "which we do not create against a deployed Supabase.",
    );
  }
  const key = getServiceRoleKey(supabaseUrl);
  // Deliverable, plus-addressed target (see plusAddress); the UUID keeps each
  // run's traveler distinct. This path is local-only (mailpit), but stays on the
  // same strategy as the rest of the suite.
  const email = uniqueEmail("e2e-onb");

  await ensureTravelerLinkedClient(getApiBaseUrl(), mintAdvisorAccessToken(), email);
  await confirmUser(supabaseUrl, key, email);

  return {
    email,
    callbackUrl: callbackUrl(baseURL, await mintHashedToken(supabaseUrl, key, email)),
  };
}

/**
 * A single-use `/auth/callback` URL that signs in an **already-invited** email
 * — the traveler auth user + linked client already exist (e.g. an advisor just
 * created them through the Command Center UI). Unlike freshTravelerCallbackUrl
 * this provisions NOTHING beyond confirming the user; it exists so a test can
 * drive the *second half* of ONB-1 — the invited traveler clicking their link —
 * against a client the browser flow already created. Local-only for the same
 * reason (we don't mint throwaway sessions against a deployed Supabase).
 */
export async function travelerCallbackUrlForEmail(
  baseURL: string,
  email: string,
): Promise<string> {
  const supabaseUrl = getSupabaseUrl();
  const key = getServiceRoleKey(supabaseUrl);
  if (isLocalSupabase(supabaseUrl)) {
    await confirmUser(supabaseUrl, key, email);
  }
  return callbackUrl(baseURL, await mintHashedToken(supabaseUrl, key, email));
}
