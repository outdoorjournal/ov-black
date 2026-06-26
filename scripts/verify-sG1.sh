#!/usr/bin/env bash
# scripts/verify-sG1.sh — single-command slice verification for M004/G1
# (Status-aware mutation gates — booked/finalized immutability).
#
# Runs the G1 acceptance bullets as pytest node ids and prints PASS/FAIL per
# bullet, then static guards that the gate + lock_reason surfaces are wired in.
# The pure-unit matrix bullets run anywhere; the DB-backed bullets self-skip
# without a local Supabase (127.0.0.1:54322) — run `supabase start` first to
# exercise them.
#
# Environment:
#   None required.
#
# Exit codes:
#   0   all acceptance bullets passed (or skipped for lack of local DB)
#   1   any bullet failed
#
# Output is prefixed with [verify-sG1] so the log greps clean.

set -euo pipefail

PREFIX="[verify-sG1]"
REPO_ROOT="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." && pwd )"
API_DIR="${REPO_ROOT}/apps/api"
SERVICE_FILE="${API_DIR}/app/services/itineraries.py"
ROUTER_FILE="${API_DIR}/app/routers/itineraries.py"
AGENT_TOOL_FILE="${REPO_ROOT}/apps/agent/src/agent/tools/mutations.py"
GATE_TESTS="tests/test_node_status_gate.py"
ROUTER_TESTS="tests/test_itineraries.py"

log()  { printf '%s %s\n' "${PREFIX}" "$*"; }
warn() { printf '%s WARN: %s\n' "${PREFIX}" "$*" >&2; }
fail() { printf '%s FAIL: %s\n' "${PREFIX}" "$*" >&2; exit 1; }

require_cmd() { command -v "$1" >/dev/null 2>&1 || fail "required command not found on PATH: $1"; }
require_cmd uv

PASSED=0
FAILED=0

run_check() {
  local label=$1
  local nodeid=$2
  log "─────────────────────────────────────────────"
  log "Check: ${label}"
  if ( cd "${API_DIR}" && uv run pytest -q --no-header "${nodeid}" ); then
    PASSED=$((PASSED + 1))
    log "PASS: ${label}"
  else
    FAILED=$((FAILED + 1))
    warn "FAIL: ${label}"
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

# "tests cover every status × actor cell" — the pure matrix (runs without a DB).
run_check "pre-firmed statuses freely editable by every actor (unit matrix)" \
          "${GATE_TESTS}::test_gate_allows_any_actor_on_pre_firmed"
run_check "firmed nodes immutable to traveler/agent/system (unit matrix)" \
          "${GATE_TESTS}::test_gate_blocks_non_advisor_on_firmed"
run_check "advisor pure status change allowed on firmed (unit matrix)" \
          "${GATE_TESTS}::test_gate_allows_advisor_pure_status_change_on_firmed"
run_check "advisor field-edit on firmed refused — demote first (unit matrix)" \
          "${GATE_TESTS}::test_gate_blocks_advisor_field_edit_on_firmed"

# "A booked node refuses traveler/agent edits with a crafted message."
run_check "traveler edit of a booked node refused (service)" \
          "${GATE_TESTS}::test_traveler_edit_of_booked_node_refused"
run_check "agent status flip of a confirmed node refused (service)" \
          "${GATE_TESTS}::test_agent_status_flip_of_confirmed_node_refused"

# "advisor demotion works + is logged."
run_check "advisor demotion works and writes an attributed history row (service)" \
          "${GATE_TESTS}::test_advisor_demotion_works_and_is_logged"
run_check "advisor field-edit on booked refused until demoted (service)" \
          "${GATE_TESTS}::test_advisor_field_edit_on_booked_node_refused"
run_check "demote-then-edit reopens the node (service)" \
          "${GATE_TESTS}::test_demote_then_edit_flow"
run_check "a firmed node can't be hard-deleted by anyone (service)" \
          "${GATE_TESTS}::test_delete_of_booked_node_refused_for_all"

# "Per-node lock_reason exposed so the agent can explain."
run_check "lock_reason rides on the graph-read row (service)" \
          "${GATE_TESTS}::test_lock_reason_rides_on_graph_read"
run_check "lock_reason serializes through the graph-read HTTP response (router)" \
          "${ROUTER_TESTS}::test_graph_read_serializes_lock_reason"

# "Agent update_node_status inherits the gate; refusals return a crafted reason."
run_check "STATUS_LOCKED maps to 409 over HTTP (router)" \
          "${ROUTER_TESTS}::test_patch_node_status_locked_maps_to_409"
run_check "advisor caller is stamped ADVISOR on PATCH (router)" \
          "${ROUTER_TESTS}::test_patch_node_stamps_advisor_when_role_advisor"
run_check "traveler/agent caller stays USER on PATCH (router)" \
          "${ROUTER_TESTS}::test_patch_node_stamps_user_for_non_advisor"

# ── Static guards: the gate + lock_reason surfaces are wired in ──────────────
guard "STATUS_LOCKED outcome defined in the service" "${SERVICE_FILE}" 'STATUS_LOCKED = "status_locked"'
guard "_check_status_gate defined in the service" "${SERVICE_FILE}" "def _check_status_gate"
guard "compute_lock_reason defined in the service" "${SERVICE_FILE}" "def compute_lock_reason"
guard "update_node calls the status gate" "${SERVICE_FILE}" "_check_status_gate("
guard "router maps STATUS_LOCKED" "${ROUTER_FILE}" "ItineraryOutcome.STATUS_LOCKED"
guard "NodeResponse exposes lock_reason" "${ROUTER_FILE}" "lock_reason: str | None"
guard "agent tool documents the status_locked refusal" "${AGENT_TOOL_FILE}" "status_locked"

# ── Summary ──────────────────────────────────────────────────────────────────
log "─────────────────────────────────────────────"
log "Summary: ${PASSED} passed, ${FAILED} failed"
if (( FAILED > 0 )); then
  fail "${FAILED} acceptance bullet(s) failed."
fi
log "All G1 acceptance bullets passed."
exit 0
