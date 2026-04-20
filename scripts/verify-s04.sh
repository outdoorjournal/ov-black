#!/usr/bin/env bash
# scripts/verify-s04.sh — single-command slice verification for S04.
#
# Hard-fails (not skips) when local Supabase is unreachable: S04's
# acceptance criteria require real SQLAlchemy writes to agent_sessions
# and agent_turns (two-transaction SSE discipline + retry bookkeeping),
# so there is no graceful skip path — no DB, no verification.
#
# Runs apps/api/tests/test_s04_slice_acceptance.py through pytest and
# prints PASS/FAIL per acceptance bullet so an operator (or CI) can see
# at a glance which slice invariant broke.
#
# Environment:
#   None required. ``supabase start`` must be running on the default
#   local Postgres port (127.0.0.1:54322).
#
# Exit codes:
#   0   all acceptance bullets passed
#   1   any check failed or local Supabase is unreachable
#
# Output is structured and prefixed with [verify-s04] so the log greps clean.

set -euo pipefail

PREFIX="[verify-s04]"
REPO_ROOT="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." && pwd )"
API_DIR="${REPO_ROOT}/apps/api"
LOCAL_DB_HOST="127.0.0.1"
LOCAL_DB_PORT="54322"

log()  { printf '%s %s\n' "${PREFIX}" "$*"; }
warn() { printf '%s WARN: %s\n' "${PREFIX}" "$*" >&2; }
fail() { printf '%s FAIL: %s\n' "${PREFIX}" "$*" >&2; exit 1; }

require_cmd() {
  local cmd=$1
  command -v "${cmd}" >/dev/null 2>&1 || fail "required command not found on PATH: ${cmd}"
}

require_cmd uv
require_cmd nc

# ── Hard precondition: local Supabase must be running ────────────────────────
log "Precondition: probing ${LOCAL_DB_HOST}:${LOCAL_DB_PORT} (local Supabase Postgres)"
if ! nc -z "${LOCAL_DB_HOST}" "${LOCAL_DB_PORT}" >/dev/null 2>&1; then
  fail "local Supabase Postgres is not reachable on ${LOCAL_DB_HOST}:${LOCAL_DB_PORT} — run 'supabase start' first."
fi
log "PASS: Supabase Postgres is reachable."

# ── Acceptance bullets — one per slice demo line ─────────────────────────────
# Each bullet maps to a single pytest node id under
# tests/test_s04_slice_acceptance.py. We run them one at a time so the
# PASS/FAIL summary is bullet-granular rather than file-granular.
PASSED=0
FAILED=0

run_check() {
  local label=$1
  local nodeid=$2
  log "─────────────────────────────────────────────"
  log "Check: ${label}"
  if (
    cd "${API_DIR}" \
      && uv run pytest -q --no-header "tests/test_s04_slice_acceptance.py::${nodeid}"
  ); then
    PASSED=$((PASSED + 1))
    log "PASS: ${label}"
  else
    FAILED=$((FAILED + 1))
    warn "FAIL: ${label}"
  fi
}

run_check "seeded VoodooDoll snapshot lands in the AgentCore system prompt" \
          "test_seeded_voodoo_doll_loads_into_first_turn"
run_check "scripted 5-turn onboarding persists all 10 rows with stable agentcore_session_id" \
          "test_scripted_five_turn_onboarding_persists_all_turns"
run_check "first_token_ms recorded on the assistant row and under the 2000 ms budget" \
          "test_first_token_ms_recorded_under_budget"
run_check "throttling on turn 3 triggers a silent retry with no error frame" \
          "test_throttling_on_turn_3_triggers_silent_retry_without_frame_loss"
run_check "retries exhausted surfaces the crafted fallback frame + error turn row" \
          "test_retries_exhausted_surfaces_crafted_fallback"
run_check "VoodooDoll sensitive context never appears in log records" \
          "test_voodoo_doll_context_never_appears_in_logs"

# ── Summary ──────────────────────────────────────────────────────────────────
log "────────────────────────────────────────────────"
log "Summary: ${PASSED} passed, ${FAILED} failed"

if (( FAILED > 0 )); then
  fail "${FAILED} acceptance bullet(s) failed."
fi

log "All S04 acceptance bullets passed."
exit 0
