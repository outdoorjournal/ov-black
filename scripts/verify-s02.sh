#!/usr/bin/env bash
# scripts/verify-s02.sh — single-command slice verification for S02.
#
# Hard-fails (not skips) when local Supabase is unreachable: this slice's
# acceptance criteria are genuinely DB-gated (graph spine + history rows),
# unlike S01 where the authed probe could soft-skip on a missing JWT.
#
# Runs apps/api/tests/test_s02_slice_acceptance.py through pytest and
# prints PASS/FAIL per acceptance bullet so an operator (or CI) can see at
# a glance which slice invariant broke.
#
# Environment:
#   None required. ``supabase start`` must be running on the default
#   local Postgres port (127.0.0.1:54322).
#
# Exit codes:
#   0   all acceptance bullets passed
#   1   any check failed or local Supabase is unreachable
#
# Output is structured and prefixed with [verify-s02] so the log greps clean.

set -euo pipefail

PREFIX="[verify-s02]"
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
# tests/test_s02_slice_acceptance.py. We run them one at a time so the
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
      && uv run pytest -q --no-header "tests/test_s02_slice_acceptance.py::${nodeid}"
  ); then
    PASSED=$((PASSED + 1))
    log "PASS: ${label}"
  else
    FAILED=$((FAILED + 1))
    warn "FAIL: ${label}"
  fi
}

run_check "POST /itinerary creates a graph" \
          "test_post_itinerary_creates_graph"
run_check "search_inventory(keyword='como') returns OV-sourced items" \
          "test_search_inventory_keyword_como_returns_ov_items"
run_check "mock-scoped search returns fixture items in same InventoryItem shape" \
          "test_search_inventory_mock_scope_returns_same_shape"
run_check "GET /itinerary/{id} returns the assembled graph view (depth + edges)" \
          "test_get_itinerary_graph_returns_assembled_view"
run_check "every node + edge mutation produces a history row" \
          "test_every_mutation_produces_history_row"
run_check "inventory-sourced nodes carry source + source_id; asymmetry is rejected" \
          "test_inventory_sourced_nodes_carry_source_and_source_id"

# ── Summary ──────────────────────────────────────────────────────────────────
log "────────────────────────────────────────────────"
log "Summary: ${PASSED} passed, ${FAILED} failed"

if (( FAILED > 0 )); then
  fail "${FAILED} acceptance bullet(s) failed."
fi

log "All S02 acceptance bullets passed."
exit 0
