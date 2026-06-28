#!/usr/bin/env bash
# scripts/verify-sI3.sh — single-command slice verification for M005/I3
# (the money gate + booking workflow; D024/D-BOOK + D025/D-PAY). See
# doc/mvp-plan.md §3 (M005).
#
# Runs the I3 acceptance bullets as pytest node ids and prints PASS/FAIL per
# bullet, then static guards that the booking surfaces are wired across
# api + migration + SDKs + CLI + invariant + web. The DB-backed bullets
# self-skip without a local Supabase (127.0.0.1:54322) — run `supabase start`
# first. No credentials are required (the offer re-price + gate use a Fake
# gateway + a stand-in provider).
#
# Environment:
#   None required.
#
# Exit codes:
#   0   all acceptance bullets passed (or skipped for lack of local DB)
#   1   any bullet failed
#
# Output is prefixed with [verify-sI3] so the log greps clean.

set -euo pipefail

PREFIX="[verify-sI3]"
REPO_ROOT="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." && pwd )"
API_DIR="${REPO_ROOT}/apps/api"
MIGRATION="${REPO_ROOT}/supabase/migrations/0025_bookings.sql"
MODEL_FILE="${API_DIR}/app/models/booking.py"
SERVICE_FILE="${API_DIR}/app/services/bookings.py"
ROUTER_FILE="${API_DIR}/app/routers/bookings.py"
ITIN_SVC="${API_DIR}/app/services/itineraries.py"
MAIN_FILE="${API_DIR}/app/main.py"
API_CLIENT="${REPO_ROOT}/packages/api-client/src/index.ts"
SDK_FILE="${REPO_ROOT}/apps/cli/src/ovb/sdk.py"
CLI_CMD="${REPO_ROOT}/apps/cli/src/ovb/cli/commands/bookings.py"
INVARIANTS="${REPO_ROOT}/apps/cli/src/ovb/invariants.py"
BOOKING_PANEL="${REPO_ROOT}/apps/web/app/_components/itinerary-graph/views/horizontal/BookingPanel.tsx"
BOOK_TESTS="tests/test_bookings.py"

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

# "A node can't be booked until paid; advisor books a paid node + records a
#  confirmation → confirmed; the reconciliation invariant holds."
run_check "gate blocks unpaid, books paid, confirms, reconciles (service)" \
          "${BOOK_TESTS}::test_money_gate_blocks_unpaid_then_books_paid_and_confirms"
# "an advisor may override onto a merely issued line — logged — and reconcile flags it."
run_check "override books on issued line, reconcile flags it (service)" \
          "${BOOK_TESTS}::test_override_books_on_issued_line_and_reconcile_flags_it"
# "a flight MUST re-price before booking (needs a fresh offer)."
run_check "flight requires a fresh offer to book (service)" \
          "${BOOK_TESTS}::test_flight_requires_fresh_offer_then_books_via_snapshot"
# "a flight re-prices LIVE through the provider and surfaces the delta (D024)."
run_check "flight re-prices live via provider + delta (service)" \
          "${BOOK_TESTS}::test_flight_reprices_live_via_provider_and_surfaces_delta"
# "a lapsed held offer can't be re-priced in place / can't book."
run_check "gone offer is a conflict (service)" \
          "${BOOK_TESTS}::test_provider_offer_gone_is_conflict"
run_check "expired offer refuses booking (service)" \
          "${BOOK_TESTS}::test_expired_offer_refuses_booking"
# "the money gate can't be bypassed via a direct update_node status flip."
run_check "update_node refuses the booking bypass (service)" \
          "${BOOK_TESTS}::test_update_node_refuses_direct_booking_bypass"

# HTTP contract: book 200 / 403 / 401 / 409, reconciliation read gate.
run_check "POST /book returns the booking (router)" "${BOOK_TESTS}::test_book_endpoint_200"
run_check "POST /book is advisor-only 403 (router)" "${BOOK_TESTS}::test_book_endpoint_advisor_only_403"
run_check "POST /book requires a JWT 401 (router)" "${BOOK_TESTS}::test_book_endpoint_requires_jwt"
run_check "POST /book maps the money gate to 409 (router)" \
          "${BOOK_TESTS}::test_book_endpoint_money_gate_409"
run_check "GET /reconciliation 200 for advisor (router)" \
          "${BOOK_TESTS}::test_reconciliation_endpoint_200_for_advisor"
run_check "GET /reconciliation forbidden for stranger (router)" \
          "${BOOK_TESTS}::test_reconciliation_endpoint_forbidden_for_stranger"

# ── Static guards: surfaces are wired in ─────────────────────────────────────
guard "migration 0025 node_offers present" "${MIGRATION}" "create table if not exists public.node_offers"
guard "migration 0025 bookings present" "${MIGRATION}" "create table if not exists public.bookings"
guard "one-live-booking-per-node invariant" "${MIGRATION}" "bookings_one_per_node"
guard "NodeOffer + Booking models present" "${MODEL_FILE}" "class Booking"
guard "book_node money gate present" "${SERVICE_FILE}" "async def book_node"
guard "refresh_offer re-price present" "${SERVICE_FILE}" "async def refresh_offer"
guard "record_confirmation present" "${SERVICE_FILE}" "async def record_confirmation"
guard "reconciliation invariant present" "${SERVICE_FILE}" "async def reconcile_itinerary"
guard "update_node bypass closed" "${ITIN_SVC}" "use_booking_flow"
guard "CONFLICT outcome present" "${ITIN_SVC}" "CONFLICT"
guard "book endpoint registered" "${ROUTER_FILE}" "/book"
guard "confirm endpoint registered" "${ROUTER_FILE}" "/confirm"
guard "reconciliation endpoint registered" "${ROUTER_FILE}" "/reconciliation"
guard "offer-refresh endpoint registered" "${ROUTER_FILE}" "/offers/refresh"
guard "bookings router registered in app" "${MAIN_FILE}" "bookings_router"
guard "api-client bookNode wrapper present" "${API_CLIENT}" "export async function bookNode"
guard "api-client getReconciliation wrapper present" "${API_CLIENT}" "export async function getReconciliation"
guard "ovb SDK book_node present" "${SDK_FILE}" "async def book_node"
guard "ovb CLI bookings group present" "${CLI_CMD}" "def book"
guard "money_gate_reconciles invariant implemented" "${INVARIANTS}" "report: gm.ReconciliationResponse"
guard "web BookingPanel present" "${BOOKING_PANEL}" "BookingPanel"

# ── Summary ──────────────────────────────────────────────────────────────────
log "─────────────────────────────────────────────"
log "Summary: ${PASSED} passed, ${FAILED} failed"
if (( FAILED > 0 )); then
  fail "${FAILED} acceptance bullet(s) failed."
fi
log "All I3 acceptance bullets passed."
exit 0
