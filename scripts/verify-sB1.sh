#!/usr/bin/env bash
# scripts/verify-sB1.sh — single-command slice verification for M002/B1
# (Google Places live inventory adapter).
#
# Runs the B1 acceptance bullets as pytest node ids (offline, deterministic —
# every test feeds recorded Places API (New) fixtures through httpx.MockTransport)
# and prints PASS/FAIL per bullet. Then, when staging creds are present, runs an
# OPTIONAL live probe against a deployed environment with a real Google Places
# key to confirm the provider returns a real, geo-anchored place end-to-end.
#
# Environment:
#   None required for the offline bullets.
#   Optional live probe (soft-skips when unset):
#     STAGING_API_URL        e.g. https://staging-api.ov.example
#     OV_BLACK_STAGING_JWT   advisor/agent JWT (see scripts/mint-jwt.sh)
#   The live probe also needs the staging deploy to have `google_places` in
#   INVENTORY_PROVIDERS_ENABLED and a GOOGLE_PLACES_API_KEY secret.
#
# Exit codes:
#   0   all offline acceptance bullets passed (live probe is best-effort)
#   1   any offline bullet failed
#
# Output is structured and prefixed with [verify-sB1] so the log greps clean.

set -euo pipefail

PREFIX="[verify-sB1]"
REPO_ROOT="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." && pwd )"
API_DIR="${REPO_ROOT}/apps/api"
ROUTER_FILE="${API_DIR}/app/routers/integrations/google_places.py"
PROVIDER_TESTS="tests/test_inventory_google_places_provider.py"
ROUTER_TESTS="tests/test_integrations.py"

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

# "Agent proposes a real restaurant card by name+geo": a dining place normalizes
# to a MealItem carrying a title (name) + geo location.
run_check "restaurant normalizes to a name+geo MealItem" \
          "${PROVIDER_TESTS}::test_normalize_meal_happy_path"

# "provenance source='google_places'": classified search results carry the source.
run_check "search results carry provenance source='google_places'" \
          "${PROVIDER_TESTS}::test_search_happy_path_classifies_items"

# "restaurant CARD": a proposed MealItem maps to typed MealCardAttrs metadata.
run_check "restaurant maps to a typed meal card (cuisine/price/geo)" \
          "tests/test_card_mapping.py::test_meal_metadata_shape_matches_frontend_contract"

# Attractions classify as experiences (meal vs. experience split is real).
run_check "tourist attraction classifies as an experience" \
          "${PROVIDER_TESTS}::test_normalize_experience_happy_path"

# "stub path removed": the live router maps a real Places response end-to-end.
run_check "live router maps a real Text Search response" \
          "${ROUTER_TESTS}::test_google_places_search_maps_results"

# Degrade discipline: no key / upstream failure ⇒ [] (never 5xx the page).
run_check "no credentials degrades to [] (not a crash)" \
          "${PROVIDER_TESTS}::test_search_no_credentials_returns_empty"

# Secret discipline: the API key never lands in a log record.
run_check "API key is never logged" \
          "${PROVIDER_TESTS}::test_api_key_never_logged"

# ── Static guard: the canned stub catalogue is gone ──────────────────────────
log "─────────────────────────────────────────────"
log "Check: stub catalogue removed from the integration router"
if grep -q "_CATALOGUE" "${ROUTER_FILE}"; then
  FAILED=$((FAILED + 1))
  warn "FAIL: ${ROUTER_FILE} still references _CATALOGUE (stub not removed)"
else
  PASSED=$((PASSED + 1))
  log "PASS: stub catalogue removed"
fi

# ── Summary (offline) ────────────────────────────────────────────────────────
log "─────────────────────────────────────────────"
log "Summary: ${PASSED} passed, ${FAILED} failed"
if (( FAILED > 0 )); then
  fail "${FAILED} acceptance bullet(s) failed."
fi
log "All B1 offline acceptance bullets passed."

# ── Optional live probe (best-effort) ────────────────────────────────────────
if [[ -n "${STAGING_API_URL:-}" && -n "${OV_BLACK_STAGING_JWT:-}" ]]; then
  require_cmd curl
  log "─────────────────────────────────────────────"
  log "Live probe: GET ${STAGING_API_URL}/search-inventory?source=google_places&kinds=meal&keyword=sushi+in+Tokyo"
  body="$(curl -fsS \
    -H "Authorization: Bearer ${OV_BLACK_STAGING_JWT}" \
    --get "${STAGING_API_URL}/search-inventory" \
    --data-urlencode "source=google_places" \
    --data-urlencode "kinds=meal" \
    --data-urlencode "keyword=sushi in Tokyo" 2>/dev/null || true)"
  if [[ -z "${body}" ]]; then
    warn "live probe got no response (deploy may lack google_places / a key) — skipping"
  elif printf '%s' "${body}" | grep -q '"source":"google_places"'; then
    log "PASS (live): a real google_places item came back"
  else
    warn "live probe returned no google_places items — check INVENTORY_PROVIDERS_ENABLED + GOOGLE_PLACES_API_KEY"
  fi
else
  log "Live staging probe skipped (set STAGING_API_URL + OV_BLACK_STAGING_JWT to enable)."
fi

exit 0
