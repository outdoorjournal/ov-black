#!/usr/bin/env bash
# scripts/verify-sV1.sh — single-command slice verification for M003/V1
# (Party member model — durable, household-scoped traveler identity).
#
# Runs the V1 acceptance bullets as pytest node ids (gated on a local Supabase
# Postgres; the integration tests skip cleanly when it is absent) and prints
# PASS/FAIL per bullet, then static guards that the surfaces are wired in.
#
# Environment:
#   None required. The DB-backed bullets self-skip without local Supabase
#   (127.0.0.1:54322) — run `supabase start` first to exercise them.
#
# Exit codes:
#   0   all acceptance bullets passed (or skipped for lack of local DB)
#   1   any bullet failed
#
# Output is prefixed with [verify-sV1] so the log greps clean.

set -euo pipefail

PREFIX="[verify-sV1]"
REPO_ROOT="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." && pwd )"
API_DIR="${REPO_ROOT}/apps/api"
MAIN_FILE="${API_DIR}/app/main.py"
AGENT_TOOLS_FILE="${REPO_ROOT}/apps/agent/src/agent/tools/__init__.py"
MIGRATION="${REPO_ROOT}/supabase/migrations/0019_party_members.sql"
SERVICE_TESTS="tests/test_party_members_service.py"
ROUTER_TESTS="tests/test_party_members_router.py"
AGENT_TESTS="tests/test_agent_internal_router.py"

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

# ── Acceptance bullets ───────────────────────────────────────────────────────

# "Traveler record persists per member; advisor reads it" — create + list, with
# identity fields + provenance round-tripping.
run_check "member persists with fields + provenance, lists primary-first (service)" \
          "${SERVICE_TESTS}::test_create_persists_fields_and_lists_primary_first"
run_check "advisor creates + lists a member over HTTP (router)" \
          "${ROUTER_TESTS}::test_advisor_creates_and_lists_member"

# "Remember previous travelers" — one durable member, reused across two trips.
run_check "the same member is reused across two itineraries (service)" \
          "${SERVICE_TESTS}::test_member_is_reused_across_two_itineraries"

# Collaboration — three actors author the same roster.
run_check "traveler self-service create + list (router)" \
          "${ROUTER_TESTS}::test_traveler_self_service_create_and_list"
run_check "agent records a member, actor fixed to agent (router)" \
          "${AGENT_TESTS}::test_post_party_member_with_valid_token_stamps_agent_actor"

# Authorization — owner scoping + collapse + role gate.
run_check "cross-advisor read collapses to 404 (router)" \
          "${ROUTER_TESTS}::test_advisor_cannot_read_unowned_client_collapses_404"
run_check "client role is forbidden on the advisor route (router)" \
          "${ROUTER_TESTS}::test_client_role_is_forbidden_on_advisor_route"

# Soft-delete keeps history; one-primary invariant.
run_check "archive soft-deletes + hides from active (service)" \
          "${SERVICE_TESTS}::test_archive_soft_deletes_and_hides_from_active"
run_check "at most one active primary per client (service)" \
          "${SERVICE_TESTS}::test_only_one_active_primary_per_client"

# "Agent can reference party constraints in Fill" — member dietary/mobility flow in.
run_check "member dietary/mobility flow into Fill constraints (service)" \
          "${SERVICE_TESTS}::test_member_constraints_flow_into_fill"

# Agent read — the active roster is in /agent/context.
run_check "active roster surfaces in agent context (service)" \
          "${SERVICE_TESTS}::test_agent_context_surfaces_active_roster_only"

# ── Static guards: surfaces are wired in ─────────────────────────────────────
log "─────────────────────────────────────────────"
log "Check: party_members router registered in main.py"
if grep -q "party_members_router" "${MAIN_FILE}"; then
  PASSED=$((PASSED + 1)); log "PASS: party_members_router is included in the FastAPI app"
else
  FAILED=$((FAILED + 1)); warn "FAIL: ${MAIN_FILE} does not include party_members_router"
fi

log "─────────────────────────────────────────────"
log "Check: agent /party-members path is whitelisted (bypasses Supabase JWT)"
if grep -q "/agent/party-members" "${MAIN_FILE}"; then
  PASSED=$((PASSED + 1)); log "PASS: /agent/party-members is in PUBLIC_PATHS"
else
  FAILED=$((FAILED + 1)); warn "FAIL: ${MAIN_FILE} does not whitelist /agent/party-members"
fi

log "─────────────────────────────────────────────"
log "Check: record_party_member tool registered in the agent bundles"
if grep -q "record_party_member" "${AGENT_TOOLS_FILE}"; then
  PASSED=$((PASSED + 1)); log "PASS: record_party_member is in the agent tool registry"
else
  FAILED=$((FAILED + 1)); warn "FAIL: ${AGENT_TOOLS_FILE} does not register record_party_member"
fi

log "─────────────────────────────────────────────"
log "Check: migration 0019 present"
if [[ -f "${MIGRATION}" ]]; then
  PASSED=$((PASSED + 1)); log "PASS: ${MIGRATION#${REPO_ROOT}/} exists"
else
  FAILED=$((FAILED + 1)); warn "FAIL: migration 0019 missing"
fi

# ── Summary ──────────────────────────────────────────────────────────────────
log "─────────────────────────────────────────────"
log "Summary: ${PASSED} passed, ${FAILED} failed"
if (( FAILED > 0 )); then
  fail "${FAILED} acceptance bullet(s) failed."
fi
log "All V1 acceptance bullets passed."
exit 0
