#!/usr/bin/env bash
# scripts/verify-f2.sh — end-to-end smoke for M001/F2 (real staging deploy).
#
# verify-s01.sh proves the container is *up* (public /health 200, authed /health 401).
# That is necessary but NOT sufficient: a task whose DATABASE_URL or Supabase JWT env
# is missing still answers /health 200 while every real request 500s. F2's whole point
# is a *functioning* deploy, so this script drives an authenticated, DB-backed path and
# fails if the data plane is broken — exactly the gaps the F2 CDK wiring closes.
#
# Runs, in order, against a DEPLOYED staging API:
#   1. GET  /openapi.json          → 200   (app booted, routing live)
#   2. GET  /health                → 200   (ALB target healthy)
#   3. GET  /health/authed (no JWT)→ 401   (JWT middleware enforced)
#   4. GET  /health/authed (+JWT)  → 200   (Supabase JWKS/issuer wired — data-plane auth)
#   5. GET  /me/itineraries (+JWT) → 200 + body has "itineraries"
#                                          (resolves a client row + queries Postgres →
#                                           proves DATABASE_URL is real, not localhost)
#
# Checks 4–5 are the F2 acceptance core. They SKIP (not fail) when no JWT is supplied,
# but skipping leaves the deploy unproven — supply OV_BLACK_STAGING_JWT to make F2 green.
# Mint one with: OV_BLACK_STAGING_JWT="$(SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=... \
#   scripts/mint-jwt.sh --email you@example.com --role client)".
#
# The "magic-link email arrives" half of F2 acceptance is a human check (a real inbox)
# and is NOT automated here — see doc/runbooks/staging-deploy.md §Verify.
#
# Environment:
#   STAGING_API_URL        Base URL of the staging ALB (required). Example:
#                          http://ov-black-api-staging-xxxxxxx.us-east-2.elb.amazonaws.com
#   OV_BLACK_STAGING_JWT   Supabase-issued JWT for checks 4–5. Any valid user works
#                          (a 200 runs the DB query regardless of client-row existence).
#
# Exit codes:
#   0   all required checks passed (checks 4–5 may be skipped if no JWT)
#   1   any check failed or a required dependency is missing
#
# Output is prefixed with [verify-f2] so it is easy to grep in CI/operator logs.

set -euo pipefail

PREFIX="[verify-f2]"
REPO_ROOT="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." && pwd )"
cd "${REPO_ROOT}"

log()  { printf '%s %s\n' "${PREFIX}" "$*"; }
warn() { printf '%s WARN: %s\n' "${PREFIX}" "$*" >&2; }
fail() { printf '%s FAIL: %s\n' "${PREFIX}" "$*" >&2; exit 1; }

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "required command not found on PATH: $1"
}
require_cmd curl

STAGING_API_URL="${STAGING_API_URL:-}"
if [[ -z "${STAGING_API_URL}" ]]; then
  fail "STAGING_API_URL is required (e.g. export STAGING_API_URL=http://<alb-dns>)."
fi
STAGING_API_URL="${STAGING_API_URL%/}"  # strip trailing slash for predictable joins

PASSED=0
FAILED=0
SKIPPED=0
record_pass() { PASSED=$((PASSED + 1));  log  "PASS: $*"; }
record_fail() { FAILED=$((FAILED + 1));  warn "FAIL: $*"; }
record_skip() { SKIPPED=$((SKIPPED + 1)); warn "SKIP: $*"; }

# Prints just the HTTP status; never exits non-zero on an HTTP error.
http_status() {
  local url=$1; shift
  curl --silent --show-error --output /dev/null --write-out '%{http_code}' \
       --max-time 20 "$@" "${url}"
}

# Writes the response body to $1 and prints the HTTP status.
http_status_body() {
  local body_file=$1 url=$2; shift 2
  curl --silent --show-error --output "${body_file}" --write-out '%{http_code}' \
       --max-time 20 "$@" "${url}"
}

# ── Check 1: OpenAPI surface reachable (app booted + routing live) ────────────
log "Check 1/5: GET ${STAGING_API_URL}/openapi.json (expect 200)"
status=$(http_status "${STAGING_API_URL}/openapi.json" || echo "000")
if [[ "${status}" == "200" ]]; then
  record_pass "GET /openapi.json → 200"
else
  record_fail "GET /openapi.json → ${status} (expected 200)"
fi

# ── Check 2: public /health (ALB target healthy) ─────────────────────────────
log "Check 2/5: GET ${STAGING_API_URL}/health (expect 200)"
status=$(http_status "${STAGING_API_URL}/health" || echo "000")
if [[ "${status}" == "200" ]]; then
  record_pass "GET /health → 200"
else
  record_fail "GET /health → ${status} (expected 200)"
fi

# ── Check 3: /health/authed without a JWT (middleware enforced) ──────────────
log "Check 3/5: GET ${STAGING_API_URL}/health/authed without Authorization (expect 401)"
status=$(http_status "${STAGING_API_URL}/health/authed" || echo "000")
if [[ "${status}" == "401" ]]; then
  record_pass "GET /health/authed (no JWT) → 401"
else
  record_fail "GET /health/authed (no JWT) → ${status} (expected 401)"
fi

# ── Checks 4–5: the data-plane proofs (need a JWT) ───────────────────────────
if [[ -z "${OV_BLACK_STAGING_JWT:-}" ]]; then
  record_skip "OV_BLACK_STAGING_JWT not set — skipping checks 4–5 (Supabase-auth + DB proofs)."
  warn "Deploy is UNPROVEN without these. See the script header to mint a JWT."
else
  AUTH_HEADER="Authorization: Bearer ${OV_BLACK_STAGING_JWT}"

  # Check 4: authed health → proves the JWKS/issuer env reaches the app and a real
  # Supabase token verifies (catches the SUPABASE_JWT JSON-blob-vs-flat-env gap).
  log "Check 4/5: GET ${STAGING_API_URL}/health/authed with Bearer JWT (expect 200)"
  status=$(http_status "${STAGING_API_URL}/health/authed" -H "${AUTH_HEADER}" || echo "000")
  if [[ "${status}" == "200" ]]; then
    record_pass "GET /health/authed (valid JWT) → 200"
  else
    record_fail "GET /health/authed (valid JWT) → ${status} (expected 200; 401 ⇒ SUPABASE_JWKS_URL/ISSUER not wired)"
  fi

  # Check 5: a DB-backed read. A 200 means the app resolved the caller's client row
  # and queried Postgres — i.e. DATABASE_URL points at the real DB, not the
  # localhost:54322 default. A 500 here is the signature of a missing DATABASE_URL.
  log "Check 5/5: GET ${STAGING_API_URL}/me/itineraries with Bearer JWT (expect 200 + 'itineraries')"
  body_file=$(mktemp)
  trap 'rm -f "${body_file}"' EXIT
  status=$(http_status_body "${body_file}" "${STAGING_API_URL}/me/itineraries" -H "${AUTH_HEADER}" || echo "000")
  if [[ "${status}" == "200" ]] && grep -q '"itineraries"' "${body_file}"; then
    record_pass "GET /me/itineraries (valid JWT) → 200 with itineraries payload (DB reachable)"
  else
    record_fail "GET /me/itineraries (valid JWT) → ${status} (expected 200; 500 ⇒ DATABASE_URL not wired / DB unreachable)"
  fi
fi

# ── Summary ──────────────────────────────────────────────────────────────────
log "────────────────────────────────────────────────"
log "Summary: ${PASSED} passed, ${FAILED} failed, ${SKIPPED} skipped"
log "Reminder: the 'magic-link email arrives' acceptance is a manual inbox check (not automated)."

if (( FAILED > 0 )); then
  fail "${FAILED} check(s) failed."
fi
log "All required F2 verification checks passed."
exit 0
