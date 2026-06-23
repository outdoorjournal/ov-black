#!/usr/bin/env bash
# scripts/verify-sB6.sh — single-command slice verification for M002/B6 (AI Fill).
#
# Runs the B6 acceptance bullets as pytest node ids (offline, deterministic —
# every test feeds an in-test inventory provider through the registry, no live
# vendors) and prints PASS/FAIL per bullet. Then, when staging creds + a target
# itinerary are present, runs an OPTIONAL live probe against a deployed
# environment to confirm POST /itinerary/{id}/fill returns proposals end-to-end.
#
# Environment:
#   None required for the offline bullets.
#   Optional live probe (soft-skips when unset):
#     STAGING_API_URL        e.g. https://staging-api.ov.example
#     OV_BLACK_STAGING_JWT   advisor/agent JWT (see scripts/mint-jwt.sh)
#     FILL_ITINERARY_ID      an itinerary with located + timed nodes to fill
#     FILL_GAP_START         ISO 8601, e.g. 2026-09-12T13:00:00+09:00
#     FILL_GAP_END           ISO 8601, e.g. 2026-09-12T18:00:00+09:00
#   The live probe also needs the staging deploy to have an inventory provider
#   enabled (INVENTORY_PROVIDERS_ENABLED) that returns located items.
#
# Exit codes:
#   0   all offline acceptance bullets passed (live probe is best-effort)
#   1   any offline bullet failed
#
# Output is structured and prefixed with [verify-sB6] so the log greps clean.

set -euo pipefail

PREFIX="[verify-sB6]"
REPO_ROOT="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." && pwd )"
API_DIR="${REPO_ROOT}/apps/api"
MAIN_FILE="${API_DIR}/app/main.py"
AGENT_TOOLS_FILE="${REPO_ROOT}/apps/agent/src/agent/tools/__init__.py"
SERVICE_TESTS="tests/test_fill_service.py"
ROUTER_TESTS="tests/test_fill_router.py"
ACCEPT_TESTS="tests/test_nodes_from_inventory.py"

log()  { printf '%s %s\n' "${PREFIX}" "$*"; }
warn() { printf '%s WARN: %s\n' "${PREFIX}" "$*" >&2; }
fail() { printf '%s FAIL: %s\n' "${PREFIX}" "$*" >&2; exit 1; }

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "required command not found on PATH: $1"
}

require_cmd uv

PASSED=0
FAILED=0

run_check() {
  local label=$1
  local nodeid=$2
  log "─────────────────────────────────────────────"
  log "Check: ${label}"
  if (
    cd "${API_DIR}" \
      && uv run pytest -q --no-header "${nodeid}"
  ); then
    PASSED=$((PASSED + 1))
    log "PASS: ${label}"
  else
    FAILED=$((FAILED + 1))
    warn "FAIL: ${label}"
  fi
}

# ── Acceptance bullets ───────────────────────────────────────────────────────

# "Fill returns ranked feasible options with rationale" — a gap in Tokyo yields
# reachable meal/experience candidates; the response carries rationale + the
# source pair needed to accept.
run_check "ranked feasible candidates returned for a gap (service)" \
          "${SERVICE_TESTS}::test_fill_returns_feasible_tokyo_and_excludes_far_osaka"
run_check "endpoint returns a feasible proposal with rationale (router)" \
          "${ROUTER_TESTS}::test_fill_returns_feasible_proposal"

# "Physically-feasible" — the drive-time envelope rejects an out-of-reach
# candidate by default, and surfaces it (flagged) only when min_score is lowered.
run_check "out-of-reach candidate excluded by default" \
          "${SERVICE_TESTS}::test_fill_returns_feasible_tokyo_and_excludes_far_osaka"
run_check "far candidate surfaced-but-flagged when min_score lowered" \
          "${SERVICE_TESTS}::test_fill_surfaces_far_candidate_only_when_min_score_lowered"

# "Scoped by party constraints" — a party allergen drops the matching meal.
run_check "party allergen drops the matching meal" \
          "${SERVICE_TESTS}::test_fill_drops_meals_with_a_party_allergen"

# Content-adjacency — don't recommend a meal right after the meal you just ate.
run_check "meal right after a meal is suppressed by default" \
          "${SERVICE_TESTS}::test_fill_downranks_a_meal_right_after_a_meal"

# "Anchored on the latest analysis" — a block finding excludes those node types.
run_check "block finding excludes ruled-out node types" \
          "${SERVICE_TESTS}::test_fill_excludes_node_types_a_block_finding_rules_out"

# Honesty: no geometry ⇒ marked feasibility_unknown, not silently 'feasible'.
run_check "no located anchors ⇒ feasibility_unknown (service)" \
          "${SERVICE_TESTS}::test_fill_marks_unknown_when_no_located_anchors"
run_check "no located anchors ⇒ feasibility_unknown (router)" \
          "${ROUTER_TESTS}::test_fill_marks_unknown_without_located_anchors"

# "Accepting one adds a proposed node with provenance" — the proposal's
# (source, source_id) feed the existing from-inventory write, which creates a
# node carrying that provenance through the normal add_node path.
run_check "accept path: from-inventory creates a node with provenance" \
          "${ACCEPT_TESTS}::test_creates_flight_node_with_card_attrs"

# Auth: Fill reuses the itinerary draft-read gate.
run_check "draft-read gate forbids a stranger" \
          "${ROUTER_TESTS}::test_fill_draft_read_gate_forbids_stranger"
run_check "endpoint requires a JWT" \
          "${ROUTER_TESTS}::test_fill_requires_jwt"

# ── Static guards: Fill is wired in ──────────────────────────────────────────
log "─────────────────────────────────────────────"
log "Check: fill router registered in main.py"
if grep -q "fill_router" "${MAIN_FILE}"; then
  PASSED=$((PASSED + 1))
  log "PASS: fill_router is included in the FastAPI app"
else
  FAILED=$((FAILED + 1))
  warn "FAIL: ${MAIN_FILE} does not include fill_router"
fi

log "─────────────────────────────────────────────"
log "Check: fill_gap tool registered in the agent planning bundle"
if grep -q "fill_gap" "${AGENT_TOOLS_FILE}"; then
  PASSED=$((PASSED + 1))
  log "PASS: fill_gap is in the agent tool registry"
else
  FAILED=$((FAILED + 1))
  warn "FAIL: ${AGENT_TOOLS_FILE} does not register fill_gap"
fi

# ── Summary (offline) ────────────────────────────────────────────────────────
log "─────────────────────────────────────────────"
log "Summary: ${PASSED} passed, ${FAILED} failed"
if (( FAILED > 0 )); then
  fail "${FAILED} acceptance bullet(s) failed."
fi
log "All B6 offline acceptance bullets passed."

# ── Optional live probe (best-effort) ────────────────────────────────────────
if [[ -n "${STAGING_API_URL:-}" && -n "${OV_BLACK_STAGING_JWT:-}" \
      && -n "${FILL_ITINERARY_ID:-}" && -n "${FILL_GAP_START:-}" \
      && -n "${FILL_GAP_END:-}" ]]; then
  require_cmd curl
  log "─────────────────────────────────────────────"
  log "Live probe: POST ${STAGING_API_URL}/itinerary/${FILL_ITINERARY_ID}/fill"
  body="$(curl -fsS \
    -H "Authorization: Bearer ${OV_BLACK_STAGING_JWT}" \
    -H "Content-Type: application/json" \
    -X POST "${STAGING_API_URL}/itinerary/${FILL_ITINERARY_ID}/fill" \
    -d "{\"gap\":{\"start\":\"${FILL_GAP_START}\",\"end\":\"${FILL_GAP_END}\"}}" \
    2>/dev/null || true)"
  if [[ -z "${body}" ]]; then
    warn "live probe got no response (check itinerary id / creds) — skipping"
  elif printf '%s' "${body}" | grep -q '"proposals"'; then
    log "PASS (live): /fill returned a proposals payload"
  else
    warn "live probe returned no proposals payload — check the itinerary has located nodes + an enabled provider"
  fi
else
  log "Live staging probe skipped (set STAGING_API_URL + OV_BLACK_STAGING_JWT + FILL_ITINERARY_ID + FILL_GAP_START + FILL_GAP_END to enable)."
fi

exit 0
