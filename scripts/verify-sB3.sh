#!/usr/bin/env bash
# scripts/verify-sB3.sh — single-command slice verification for M002/B3
# (Ratehawk hotels inventory adapter).
#
# Runs the B3 acceptance bullets as pytest node ids (offline, deterministic —
# every test feeds the recorded ETG SERP fixture through httpx.MockTransport)
# and prints PASS/FAIL per bullet. Then, when staging creds are present, runs an
# OPTIONAL live probe against a deployed environment with real Ratehawk creds to
# confirm the provider returns real, geo-anchored hotel rates end-to-end.
#
# Environment:
#   None required for the offline bullets.
#   Optional live probe (soft-skips when unset):
#     STAGING_API_URL        e.g. https://staging-api.ov.example
#     OV_BLACK_STAGING_JWT   advisor/agent JWT (see scripts/mint-jwt.sh)
#     RATEHAWK_REGION_ID     ETG region id to search (default 2381 = Lake Como)
#   The live probe also needs the staging deploy to have `ratehawk` in
#   INVENTORY_PROVIDERS_ENABLED and RATEHAWK_KEY_ID / RATEHAWK_API_KEY secrets.
#
# Exit codes:
#   0   all offline acceptance bullets passed (live probe is best-effort)
#   1   any offline bullet failed
#
# Output is structured and prefixed with [verify-sB3] so the log greps clean.

set -euo pipefail

PREFIX="[verify-sB3]"
REPO_ROOT="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." && pwd )"
API_DIR="${REPO_ROOT}/apps/api"
MAIN_FILE="${API_DIR}/app/main.py"
PROVIDER_TESTS="tests/test_inventory_ratehawk_provider.py"
MAPPING_TESTS="tests/test_card_mapping.py"
ROUTER_TESTS="tests/test_search_inventory.py"

log()  { printf '%s %s\n' "${PREFIX}" "$*"; }
warn() { printf '%s WARN: %s\n' "${PREFIX}" "$*" >&2; }
fail() { printf '%s FAIL: %s\n' "${PREFIX}" "$*" >&2; exit 1; }

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "required command not found on PATH: $1"
}

# Portable "today + N days" (GNU date first, then BSD/macOS date).
future_date() {
  local days=$1
  date -u -d "+${days} days" +%Y-%m-%d 2>/dev/null || date -u -v+"${days}"d +%Y-%m-%d
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

# "search_inventory(kinds=['hotel']) returns live Ratehawk rates": a region
# search returns normalized HotelItems for each hotel in the SERP response.
run_check "region search returns HotelItems" \
          "${PROVIDER_TESTS}::test_search_region_happy_path"

# Provenance + price: a hotel normalizes to source='ratehawk' with the cheapest
# rate's display price.
run_check "hotel normalizes to a priced source='ratehawk' item" \
          "${PROVIDER_TESTS}::test_normalize_hotel_happy_path"

# Cheapest-rate headline (multi-rate hotel → lowest display amount).
run_check "multi-rate hotel headlines off the cheapest rate" \
          "${PROVIDER_TESTS}::test_normalize_picks_cheapest_rate"

# Geo search path (lat/lng → /search/serp/geo/).
run_check "coordinate search uses the geo endpoint" \
          "${PROVIDER_TESTS}::test_search_geo_uses_geo_endpoint"

# "hotel node renders room/nights/check-in": HotelItem → HotelCardAttrs.
run_check "hotel node carries room/nights/geo" \
          "${MAPPING_TESTS}::test_hotel_item_to_card_attrs_carries_room_nights_geo"
run_check "search dates render as check-in/out + nights" \
          "${MAPPING_TESTS}::test_hotel_check_in_out_recompute_nights"

# Plumbing: hotel params ride through the /search-inventory router into filters.
run_check "router forwards hotel params into filters" \
          "${ROUTER_TESTS}::test_search_forwards_hotel_params_into_filters"

# Degrade discipline: no creds / non-ok ETG envelope ⇒ [] (never 5xx the page).
run_check "no credentials degrades to [] (not a crash)" \
          "${PROVIDER_TESTS}::test_search_no_credentials_returns_empty"
run_check "non-ok ETG envelope degrades to []" \
          "${PROVIDER_TESTS}::test_search_envelope_error_returns_empty"

# Secret discipline: the API key never lands in a log record.
run_check "API key is never logged" \
          "${PROVIDER_TESTS}::test_api_key_never_logged"

# ── Static guard: the provider is wired into the registry ────────────────────
log "─────────────────────────────────────────────"
log "Check: RatehawkProvider registered in main.py"
if grep -q "RatehawkProvider" "${MAIN_FILE}"; then
  PASSED=$((PASSED + 1))
  log "PASS: RatehawkProvider is wired into the startup registry"
else
  FAILED=$((FAILED + 1))
  warn "FAIL: ${MAIN_FILE} does not register RatehawkProvider"
fi

# ── Summary (offline) ────────────────────────────────────────────────────────
log "─────────────────────────────────────────────"
log "Summary: ${PASSED} passed, ${FAILED} failed"
if (( FAILED > 0 )); then
  fail "${FAILED} acceptance bullet(s) failed."
fi
log "All B3 offline acceptance bullets passed."

# ── Optional live probe (best-effort) ────────────────────────────────────────
# NOTE: until ETG sandbox creds exist + the static-content join is wired (see
# mvp-plan §8/B3 resume hook 3), a live result confirms rate retrieval but the
# hotel name/geo come from the fixture's inlined static_vm, not a live join.
if [[ -n "${STAGING_API_URL:-}" && -n "${OV_BLACK_STAGING_JWT:-}" ]]; then
  require_cmd curl
  region_id="${RATEHAWK_REGION_ID:-2381}"
  checkin="$(future_date 30)"
  checkout="$(future_date 32)"
  log "─────────────────────────────────────────────"
  log "Live probe: GET ${STAGING_API_URL}/search-inventory?source=ratehawk&kinds=hotel&region_id=${region_id}&checkin=${checkin}&checkout=${checkout}"
  body="$(curl -fsS \
    -H "Authorization: Bearer ${OV_BLACK_STAGING_JWT}" \
    --get "${STAGING_API_URL}/search-inventory" \
    --data-urlencode "source=ratehawk" \
    --data-urlencode "kinds=hotel" \
    --data-urlencode "region_id=${region_id}" \
    --data-urlencode "checkin=${checkin}" \
    --data-urlencode "checkout=${checkout}" 2>/dev/null || true)"
  if [[ -z "${body}" ]]; then
    warn "live probe got no response (deploy may lack ratehawk / creds) — skipping"
  elif printf '%s' "${body}" | grep -q '"source":"ratehawk"'; then
    log "PASS (live): a real ratehawk hotel came back"
  else
    warn "live probe returned no ratehawk items — check INVENTORY_PROVIDERS_ENABLED + RATEHAWK_KEY_ID/RATEHAWK_API_KEY (or the region had no availability)"
  fi
else
  log "Live staging probe skipped (set STAGING_API_URL + OV_BLACK_STAGING_JWT to enable)."
fi

exit 0
