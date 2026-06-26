#!/usr/bin/env bash
# scripts/verify-sG2.sh — single-command slice verification for M004/G2
# (Itinerary fork — versioned clone with lineage; decision D-FORK).
#
# Runs the G2 acceptance bullets as pytest node ids and prints PASS/FAIL per
# bullet, then static guards that the fork surfaces are wired in. The pure-unit
# bullet runs anywhere; the DB-backed bullets self-skip without a local Supabase
# (127.0.0.1:54322) — run `supabase start` first to exercise them.
#
# Environment:
#   None required.
#
# Exit codes:
#   0   all acceptance bullets passed (or skipped for lack of local DB)
#   1   any bullet failed
#
# Output is prefixed with [verify-sG2] so the log greps clean.

set -euo pipefail

PREFIX="[verify-sG2]"
REPO_ROOT="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." && pwd )"
API_DIR="${REPO_ROOT}/apps/api"
MIGRATION="${REPO_ROOT}/supabase/migrations/0021_itinerary_fork.sql"
SERVICE_FILE="${API_DIR}/app/services/fork.py"
ROUTER_FILE="${API_DIR}/app/routers/itineraries.py"
AGENT_TOOL_FILE="${REPO_ROOT}/apps/agent/src/agent/tools/fork.py"
AGENT_REGISTRY="${REPO_ROOT}/apps/agent/src/agent/tools/__init__.py"
FORK_TESTS="tests/test_fork.py"

log()  { printf '%s %s\n' "${PREFIX}" "$*"; }
warn() { printf '%s WARN: %s\n' "${PREFIX}" "$*" >&2; }
fail() { printf '%s FAIL: %s\n' "${PREFIX}" "$*" >&2; exit 1; }

require_cmd() { command -v "$1" >/dev/null 2>&1 || fail "required command not found on PATH: $1"; }
require_cmd uv

PASSED=0
FAILED=0

run_check() {
  local label=$1 nodeid=$2
  log "─────────────────────────────────────────────"
  log "Check: ${label}"
  if ( cd "${API_DIR}" && uv run pytest -q --no-header "${nodeid}" ); then
    PASSED=$((PASSED + 1)); log "PASS: ${label}"
  else
    FAILED=$((FAILED + 1)); warn "FAIL: ${label}"
  fi
}

guard() {
  local label=$1 file=$2 needle=$3
  log "─────────────────────────────────────────────"
  log "Check: ${label}"
  if grep -q -- "${needle}" "${file}"; then
    PASSED=$((PASSED + 1)); log "PASS: ${label}"
  else
    FAILED=$((FAILED + 1)); warn "FAIL: ${label} (missing '${needle}' in ${file#${REPO_ROOT}/})"
  fi
}

# ── Acceptance bullets ───────────────────────────────────────────────────────

# "pre-booked → editable, booked/confirmed → carried locked" (status transform).
run_check "fork status transform: approved→proposed, booked/confirmed preserved (unit)" \
          "${FORK_TESTS}::test_forked_status_transform"

# "the fork is independently editable; booked nodes are present but locked;
#  lineage links each forked node to its origin."
run_check "fork clones the graph with lineage + carried-locked booking (service)" \
          "${FORK_TESTS}::test_fork_clones_graph_with_lineage"
run_check "the fork mutates independently of the baseline (service)" \
          "${FORK_TESTS}::test_fork_is_independent_of_baseline"
run_check "PostGIS location is copied into the fork (service)" \
          "${FORK_TESTS}::test_fork_copies_postgis_location"
run_check "forking a missing baseline returns NOT_FOUND (service)" \
          "${FORK_TESTS}::test_fork_missing_baseline_returns_not_found"

# HTTP contract: 201 + the fork graph, 404 missing, 403 non-forkable, 401 no JWT.
run_check "POST /fork returns 201 + the fork graph (router)" \
          "${FORK_TESTS}::test_fork_endpoint_201_returns_fork_graph"
run_check "POST /fork 404 on a missing baseline (router)" \
          "${FORK_TESTS}::test_fork_endpoint_404_when_baseline_missing"
run_check "POST /fork 403 when the caller can't fork it (router)" \
          "${FORK_TESTS}::test_fork_endpoint_403_when_not_forkable"
run_check "POST /fork requires a JWT (router)" \
          "${FORK_TESTS}::test_fork_endpoint_requires_jwt"

# ── Static guards: surfaces are wired in ─────────────────────────────────────
guard "migration 0021 present" "${MIGRATION}" "create type public.fork_status"
guard "fork service deep-copies with lineage" "${SERVICE_FILE}" "forked_from_node_id"
guard "fork endpoint registered" "${ROUTER_FILE}" '"/{itinerary_id}/fork"'
guard "fork authz gate (owner/creator/advisor)" "${ROUTER_FILE}" "assert_itinerary_forkable"
guard "agent fork_itinerary tool present" "${AGENT_TOOL_FILE}" "async def fork_itinerary"
guard "agent fork tool registered in planning bundle" "${AGENT_REGISTRY}" "fork_itinerary"

# ── Summary ──────────────────────────────────────────────────────────────────
log "─────────────────────────────────────────────"
log "Summary: ${PASSED} passed, ${FAILED} failed"
if (( FAILED > 0 )); then
  fail "${FAILED} acceptance bullet(s) failed."
fi
log "All G2 acceptance bullets passed."
exit 0
