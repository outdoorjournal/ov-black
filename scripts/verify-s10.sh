#!/usr/bin/env bash
# scripts/verify-s10.sh — single-command mechanical floor for S10.
#
# Composes the eight existing per-slice verification scripts (verify-s01.sh,
# verify-s02.sh, verify-s04.sh, verify-s05.sh, verify-s06.sh, verify-s07.sh,
# verify-s08.sh, verify-s09.sh — note verify-s03.sh intentionally does not
# exist; S03 is an advisor-flow slice without a verify script) plus a full
# repo sweep:
#
#   (a) cd apps/api && uv run pytest -q
#   (b) pnpm -C apps/web test -- --run
#   (c) pnpm -C apps/web typecheck
#   (d) pnpm -C apps/web lint
#   (e) pnpm -C apps/web build
#   (f) pnpm -C infra/cdk cdk synth --quiet
#
# Unlike verify-s09.sh, this script does NOT use vitest -t per-bullet filters.
# Per-slice bullet granularity already lives inside each verify-sNN script, so
# this one only adds the full-sweep bullets directly and delegates slice-level
# detail to the upstream scripts.
#
# Environment:
#   STAGING_API_URL        Base URL of the staging ALB. If unset, the
#                          verify-s01 bullet is SKIPPED (not failed) — the
#                          walkthrough itself will exercise the staging API,
#                          so local-only verify-s10 runs do not require
#                          staging reachability.
#   OV_BLACK_STAGING_JWT   Supabase-issued JWT for the authed probe. Same
#                          skip semantics as STAGING_API_URL.
#
# Expected runtime:
#   ~3–6 min wall-clock (eight verify-sNN subscripts + six full-sweep bullets).
#
# Exit codes:
#   0   all bullets passed (skips allowed)
#   1   any bullet failed, or a required command is missing
#
# Output is structured and prefixed with [verify-s10] so the log greps clean.
# Every FAIL line names the specific subscript or sweep target so a localized
# regression is attributable in one `grep FAIL` pass.

set -euo pipefail

PREFIX="[verify-s10]"
REPO_ROOT="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." && pwd )"
SCRIPTS_DIR="${REPO_ROOT}/scripts"
cd "${REPO_ROOT}"

log()  { printf '%s %s\n' "${PREFIX}" "$*"; }
warn() { printf '%s WARN: %s\n' "${PREFIX}" "$*" >&2; }
fail() { printf '%s FAIL: %s\n' "${PREFIX}" "$*" >&2; exit 1; }

require_cmd() {
  local cmd=$1
  command -v "${cmd}" >/dev/null 2>&1 || fail "required command not found on PATH: ${cmd}"
}

# pnpm powers 5 of the 6 full-sweep bullets; hard-require it.
# uv is checked inline before the pytest bullet so a missing uv yields a clean
# FAIL on that single bullet rather than aborting the whole run.
require_cmd pnpm

PASSED=0
FAILED=0
SKIPPED=0

record_pass() { PASSED=$((PASSED + 1)); log "PASS: $*"; }
record_fail() { FAILED=$((FAILED + 1)); warn "FAIL: $*"; }
record_skip() { SKIPPED=$((SKIPPED + 1)); warn "SKIP: $*"; }

# ── run_subscript: invoke verify-sNN.sh, record PASS/FAIL by subscript name ──
# Caller passes the full filename (e.g. "verify-s02.sh") so grep-ability is
# preserved: a single line in this script names each invoked subscript.
run_subscript() {
  local name=$1
  local path="${SCRIPTS_DIR}/${name}"
  log "────────────────────────────────────────────────"
  log "Subscript: ${name}"
  if [[ ! -x "${path}" ]]; then
    record_fail "${name} — script not found or not executable at ${path}"
    return
  fi
  if bash "${path}"; then
    record_pass "${name}"
  else
    record_fail "${name} failed"
  fi
}

# ── run_check: invoke a shell command, record PASS/FAIL by label ─────────────
run_check() {
  local label=$1
  shift
  log "────────────────────────────────────────────────"
  log "Check: ${label}"
  if "$@"; then
    record_pass "${label}"
  else
    record_fail "${label}"
  fi
}

# ─────────────────────────────────────────────────────────────────────────────
# verify-sNN subscripts (8 total — no verify-s03; confirmed absent)
# ─────────────────────────────────────────────────────────────────────────────

# verify-s01 requires live staging reachability. Skip (do not fail) when env
# is missing — the walkthrough exercises the staging API directly.
log "────────────────────────────────────────────────"
log "Subscript: verify-s01 (conditional on staging env)"
if [[ -z "${STAGING_API_URL:-}" || -z "${OV_BLACK_STAGING_JWT:-}" ]]; then
  record_skip "verify-s01 — STAGING_API_URL/OV_BLACK_STAGING_JWT not set (staging probe deferred to walkthrough)"
else
  if bash "${SCRIPTS_DIR}/verify-s01.sh"; then
    record_pass "verify-s01"
  else
    record_fail "verify-s01 failed"
  fi
fi

run_subscript "verify-s02.sh"
run_subscript "verify-s04.sh"
run_subscript "verify-s05.sh"
run_subscript "verify-s06.sh"
run_subscript "verify-s07.sh"
run_subscript "verify-s08.sh"
run_subscript "verify-s09.sh"

# ─────────────────────────────────────────────────────────────────────────────
# Full-sweep bullets (6 total — discrete so a failure localizes to one target)
# ─────────────────────────────────────────────────────────────────────────────

# (a) pytest — MUST run from apps/api (uv venv lives there; running from repo
# root picks up the wrong interpreter / no pytest). Use `bash -c` to keep the
# cwd change scoped to the invocation.
log "────────────────────────────────────────────────"
log "Check: apps/api pytest"
if ! command -v uv >/dev/null 2>&1; then
  record_fail "pytest — uv not found on PATH"
else
  if bash -c 'cd apps/api && uv run pytest -q'; then
    record_pass "apps/api pytest"
  else
    record_fail "apps/api pytest failed"
  fi
fi

# (b–e) web workspace — vitest, typecheck, lint, build
run_check "apps/web vitest" pnpm -C apps/web test -- --run
run_check "apps/web typecheck" pnpm -C apps/web typecheck
run_check "apps/web lint" pnpm -C apps/web lint
run_check "apps/web build" pnpm -C apps/web build

# (f) CDK synth
run_check "infra/cdk cdk synth" pnpm -C infra/cdk cdk synth --quiet

# ── Summary ──────────────────────────────────────────────────────────────────
log "────────────────────────────────────────────────"
log "Summary: ${PASSED} passed, ${FAILED} failed, ${SKIPPED} skipped"

if (( FAILED > 0 )); then
  fail "${FAILED} bullet(s) failed."
fi

log "All S10 mechanical-floor bullets passed."
exit 0
