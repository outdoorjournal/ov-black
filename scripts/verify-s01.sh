#!/usr/bin/env bash
# scripts/verify-s01.sh — single-command slice verification for S01.
#
# Runs, in order:
#   1. GET  <STAGING_API_URL>/health         → expect 200
#   2. GET  <STAGING_API_URL>/health/authed  → expect 401 without JWT
#   3. GET  <STAGING_API_URL>/health/authed  → expect 200 with OV_BLACK_STAGING_JWT (if provided)
#   4. pnpm -C apps/web build                → expect exit 0
#   5. pnpm -C infra/cdk cdk synth --quiet   → expect exit 0
#
# Environment:
#   STAGING_API_URL        Base URL of the staging ALB (required for checks 1–3). Example:
#                          http://ov-black-api-staging-xxxxxxx.us-east-1.elb.amazonaws.com
#   OV_BLACK_STAGING_JWT   Optional Supabase-issued JWT for the authed probe (check 3).
#                          If unset, check 3 is SKIPPED (not failed) and a warning is printed —
#                          minting one requires a live invite redemption out of scope for this script.
#
# Exit codes:
#   0   all required checks passed
#   1   any check failed or a required dependency is missing
#
# Output is structured and prefixed with [verify-s01] so the log is easy to grep in CI.

set -euo pipefail

PREFIX="[verify-s01]"
REPO_ROOT="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." && pwd )"
cd "${REPO_ROOT}"

log()  { printf '%s %s\n' "${PREFIX}" "$*"; }
warn() { printf '%s WARN: %s\n' "${PREFIX}" "$*" >&2; }
fail() { printf '%s FAIL: %s\n' "${PREFIX}" "$*" >&2; exit 1; }

require_cmd() {
  local cmd=$1
  command -v "${cmd}" >/dev/null 2>&1 || fail "required command not found on PATH: ${cmd}"
}

require_cmd curl
require_cmd pnpm

STAGING_API_URL="${STAGING_API_URL:-}"
if [[ -z "${STAGING_API_URL}" ]]; then
  fail "STAGING_API_URL is required (e.g. export STAGING_API_URL=http://<alb-dns>)."
fi
# Strip trailing slash so URL joins are predictable.
STAGING_API_URL="${STAGING_API_URL%/}"

PASSED=0
FAILED=0
SKIPPED=0

record_pass() { PASSED=$((PASSED + 1)); log "PASS: $*"; }
record_fail() { FAILED=$((FAILED + 1)); warn "FAIL: $*"; }
record_skip() { SKIPPED=$((SKIPPED + 1)); warn "SKIP: $*"; }

# curl helper: prints the HTTP status to stdout, never exits non-zero on HTTP error.
http_status() {
  local url=$1
  shift
  curl --silent --show-error --output /dev/null --write-out '%{http_code}' \
       --max-time 15 "$@" "${url}"
}

# ── Check 1: public /health returns 200 ───────────────────────────────────────
log "Check 1/5: GET ${STAGING_API_URL}/health (expect 200)"
status=$(http_status "${STAGING_API_URL}/health" || echo "000")
if [[ "${status}" == "200" ]]; then
  record_pass "GET /health → 200"
else
  record_fail "GET /health → ${status} (expected 200)"
fi

# ── Check 2: /health/authed returns 401 without JWT ───────────────────────────
log "Check 2/5: GET ${STAGING_API_URL}/health/authed without Authorization (expect 401)"
status=$(http_status "${STAGING_API_URL}/health/authed" || echo "000")
if [[ "${status}" == "401" ]]; then
  record_pass "GET /health/authed (no JWT) → 401"
else
  record_fail "GET /health/authed (no JWT) → ${status} (expected 401)"
fi

# ── Check 3: /health/authed returns 200 with a valid JWT (optional) ───────────
log "Check 3/5: GET ${STAGING_API_URL}/health/authed with Bearer JWT (expect 200)"
if [[ -n "${OV_BLACK_STAGING_JWT:-}" ]]; then
  status=$(http_status "${STAGING_API_URL}/health/authed" \
            -H "Authorization: Bearer ${OV_BLACK_STAGING_JWT}" || echo "000")
  if [[ "${status}" == "200" ]]; then
    record_pass "GET /health/authed (valid JWT) → 200"
  else
    record_fail "GET /health/authed (valid JWT) → ${status} (expected 200)"
  fi
else
  record_skip "OV_BLACK_STAGING_JWT not set — skipping authed probe (see script header)."
fi

# ── Check 4: web workspace build ──────────────────────────────────────────────
log "Check 4/5: pnpm -C apps/web build"
if pnpm -C apps/web build; then
  record_pass "apps/web build succeeded"
else
  record_fail "apps/web build failed"
fi

# ── Check 5: CDK synth ────────────────────────────────────────────────────────
log "Check 5/5: pnpm -C infra/cdk cdk synth --quiet"
if pnpm -C infra/cdk cdk synth --quiet; then
  record_pass "infra/cdk synth succeeded"
else
  record_fail "infra/cdk synth failed"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
log "────────────────────────────────────────────────"
log "Summary: ${PASSED} passed, ${FAILED} failed, ${SKIPPED} skipped"

if (( FAILED > 0 )); then
  fail "${FAILED} check(s) failed."
fi

log "All required S01 verification checks passed."
exit 0
