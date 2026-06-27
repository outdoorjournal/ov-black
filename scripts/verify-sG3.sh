#!/usr/bin/env bash
# scripts/verify-sG3.sh — single-command slice verification for M004/G3
# (Diff + reconcile, + the conversational fork). See doc/g3-fork-reconcile-handoff.md.
#
# Runs the G3 acceptance bullets as pytest node ids and prints PASS/FAIL per
# bullet, then static guards that the diff/reconcile surfaces are wired in across
# api + agent + web. The DB-backed bullets self-skip without a local Supabase
# (127.0.0.1:54322) — run `supabase start` first to exercise them.
#
# Environment:
#   None required.
#
# Exit codes:
#   0   all acceptance bullets passed (or skipped for lack of local DB)
#   1   any bullet failed
#
# Output is prefixed with [verify-sG3] so the log greps clean.

set -euo pipefail

PREFIX="[verify-sG3]"
REPO_ROOT="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." && pwd )"
API_DIR="${REPO_ROOT}/apps/api"
MIGRATION="${REPO_ROOT}/supabase/migrations/0022_fork_reconcile.sql"
SERVICE_FILE="${API_DIR}/app/services/fork.py"
ROUTER_FILE="${API_DIR}/app/routers/itineraries.py"
AGENT_REQ_TOOL="${REPO_ROOT}/apps/agent/src/agent/tools/request_reconcile.py"
AGENT_RECON_TOOL="${REPO_ROOT}/apps/agent/src/agent/tools/reconcile.py"
AGENT_REGISTRY="${REPO_ROOT}/apps/agent/src/agent/tools/__init__.py"
TRAVELER_CTX="${API_DIR}/app/agent/traveler_context.py"
API_CLIENT="${REPO_ROOT}/packages/api-client/src/index.ts"
DIFF_PANEL="${REPO_ROOT}/apps/web/app/_components/itinerary-graph/views/horizontal/DiffPanel.tsx"
HORIZ_VIEW="${REPO_ROOT}/apps/web/app/_components/itinerary-graph/views/horizontal/HorizontalView.tsx"
RECON_TESTS="tests/test_fork_reconcile.py"

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
  if [[ -f "${file}" ]] && grep -q -- "${needle}" "${file}"; then
    PASSED=$((PASSED + 1)); log "PASS: ${label}"
  else
    FAILED=$((FAILED + 1)); warn "FAIL: ${label} (missing '${needle}' in ${file#${REPO_ROOT}/})"
  fi
}

# ── Acceptance bullets ───────────────────────────────────────────────────────

# "diff — added/removed/changed/moved, paired by lineage; the intrinsic
#  approved→proposed demotion is NOT reported as a change."
run_check "diff buckets added/removed/changed/moved + demotion excluded (service)" \
          "${RECON_TESTS}::test_diff_buckets_added_removed_changed_moved"
run_check "diff refuses a non-fork itinerary (service)" \
          "${RECON_TESTS}::test_diff_rejects_non_fork"

# "reconcile — accept a subset into the live plan, discard the rest; live
#  itinerary reflects only accepted changes; fork → reconciled."
run_check "reconcile applies accepted, discards rest, marks fork reconciled (service)" \
          "${RECON_TESTS}::test_reconcile_applies_accepted_discards_rest"
# "booked nodes can't be changed via reconcile."
run_check "reconcile refuses a booked baseline node, reports it (service)" \
          "${RECON_TESTS}::test_reconcile_refuses_booked_baseline_node"
# "feasibility gate — refuses (or override) on a block finding."
run_check "feasibility gate blocks without override, passes with it (service)" \
          "${RECON_TESTS}::test_reconcile_feasibility_gate_blocks_without_override"

# "conversational fork — traveler requests reconciliation; advisor sees it."
run_check "request stamps then abandon clears reconcile_requested_at (service)" \
          "${RECON_TESTS}::test_request_then_abandon_stamps_and_clears"

# HTTP contract: diff 200/404/401, reconcile 200/advisor-only-403/401, request/abandon 200.
run_check "GET /diff returns the diff (router)"     "${RECON_TESTS}::test_diff_endpoint_200"
run_check "POST /reconcile returns outcomes (router)" "${RECON_TESTS}::test_reconcile_endpoint_200"
run_check "POST /reconcile is advisor-only 403 (router)" \
          "${RECON_TESTS}::test_reconcile_endpoint_advisor_only_403"
run_check "POST /request-reconcile stamps the ask (router)" \
          "${RECON_TESTS}::test_request_reconcile_endpoint_200"
run_check "POST /abandon abandons the fork (router)" "${RECON_TESTS}::test_abandon_endpoint_200"

# ── Static guards: surfaces are wired in ─────────────────────────────────────
guard "migration 0022 present" "${MIGRATION}" "reconcile_requested_at"
guard "diff_fork service present" "${SERVICE_FILE}" "async def diff_fork"
guard "reconcile_fork service present" "${SERVICE_FILE}" "async def reconcile_fork"
guard "request_reconcile + abandon_fork present" "${SERVICE_FILE}" "async def abandon_fork"
guard "GET /diff endpoint registered" "${ROUTER_FILE}" '"/{fork_id}/diff"'
guard "POST /reconcile endpoint registered" "${ROUTER_FILE}" '"/{fork_id}/reconcile"'
guard "reconcile is advisor-gated" "${ROUTER_FILE}" "reconcile_fork_endpoint"
guard "request-reconcile endpoint registered" "${ROUTER_FILE}" '"/{fork_id}/request-reconcile"'
guard "abandon endpoint registered" "${ROUTER_FILE}" '"/{fork_id}/abandon"'

# Phase 2 (agent) — the conversational fork half.
guard "agent request_reconcile tool present" "${AGENT_REQ_TOOL}" "request_reconcile"
guard "agent reconcile tool present" "${AGENT_RECON_TOOL}" "reconcile"
guard "agent fork/reconcile tools registered" "${AGENT_REGISTRY}" "request_reconcile"
guard "prompt says 'alternative version'" "${TRAVELER_CTX}" "alternative version"

# Phase 3 (web) — the diff view + banner.
guard "api-client reconcile wrappers present" "${API_CLIENT}" "reconcileFork"
guard "DiffPanel present" "${DIFF_PANEL}" "DiffPanel"
guard "alternative-version banner present" "${HORIZ_VIEW}" "alternative version"

# ── Summary ──────────────────────────────────────────────────────────────────
log "─────────────────────────────────────────────"
log "Summary: ${PASSED} passed, ${FAILED} failed"
if (( FAILED > 0 )); then
  fail "${FAILED} acceptance bullet(s) failed."
fi
log "All G3 acceptance bullets passed."
exit 0
