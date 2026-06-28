#!/usr/bin/env bash
# scripts/verify-sR1.sh — single-command verification for the cancel + refund
# booking flow (resume hook, doc/mvp-plan.md §234).
#
# Runs the cancel/refund acceptance checks as pytest node ids and prints
# PASS/FAIL per bullet, then static guards that the surfaces are wired across
# migration + models + gateway + service + router + SDKs + CLI + web, plus a
# redaction guard (refund cross-refs are never logged). The DB-backed bullets
# self-skip without a local Supabase (127.0.0.1:54322) — run `supabase start`
# first. No credentials are required (refunds use a Fake gateway).
#
# Exit codes:
#   0   all acceptance bullets passed (or skipped for lack of local DB)
#   1   any bullet failed
#
# Output is prefixed with [verify-sR1] so the log greps clean.

set -euo pipefail

PREFIX="[verify-sR1]"
REPO_ROOT="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." && pwd )"
API_DIR="${REPO_ROOT}/apps/api"
MIGRATION="${REPO_ROOT}/supabase/migrations/0028_booking_cancel_refund.sql"
MODEL_FILE="${API_DIR}/app/models/booking.py"
INVOICE_MODEL="${API_DIR}/app/models/invoice.py"
GATEWAY_BASE="${API_DIR}/app/payments/base.py"
GATEWAY_BT="${API_DIR}/app/payments/braintree_gateway.py"
SERVICE_FILE="${API_DIR}/app/services/bookings.py"
ROUTER_FILE="${API_DIR}/app/routers/bookings.py"
API_CLIENT="${REPO_ROOT}/packages/api-client/src/index.ts"
SDK_FILE="${REPO_ROOT}/apps/cli/src/ovb/sdk.py"
CLI_CMD="${REPO_ROOT}/apps/cli/src/ovb/cli/commands/bookings.py"
BOOKING_PANEL="${REPO_ROOT}/apps/web/app/_components/itinerary-graph/views/horizontal/BookingPanel.tsx"
BOOK_TESTS="tests/test_bookings.py"
PAY_TESTS="tests/test_payments.py"

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

guard_absent() {
  local label=$1 file=$2 needle=$3
  log "─────────────────────────────────────────────"
  log "Check: ${label}"
  if [[ -f "${file}" ]] && grep -q -- "${needle}" "${file}"; then
    FAILED=$((FAILED + 1)); warn "FAIL: ${label} (found '${needle}' in ${file#${REPO_ROOT}/})"
  else
    PASSED=$((PASSED + 1)); log "PASS: ${label}"
  fi
}

# ── Acceptance bullets (service) ─────────────────────────────────────────────

# "Cancel a paid booking: refund + reverse the line + demote the node, and the
#  reconciliation invariant still holds."
run_check "cancel refunds, demotes, reverses, reconciles (service)" \
          "${BOOK_TESTS}::test_cancel_refunds_demotes_reverses_and_reconciles"
# "An override (unpaid) booking cancels with no money to return."
run_check "override-unpaid cancel is not_applicable (service)" \
          "${BOOK_TESTS}::test_cancel_override_unpaid_is_not_applicable"
# "A declined refund rolls the whole cancel back (fail-closed)."
run_check "declined refund fails closed (service)" \
          "${BOOK_TESTS}::test_cancel_fails_closed_on_declined_refund"
# "A gateway error (unknown outcome) records nothing."
run_check "gateway error rolls back (service)" \
          "${BOOK_TESTS}::test_cancel_rolls_back_on_gateway_error"
# "Only a booked/confirmed node can be cancelled."
run_check "cancel refuses an unbooked node (service)" \
          "${BOOK_TESTS}::test_cancel_refuses_unbooked_node"
# "A cancelled node is re-bookable (partial unique index)."
run_check "node re-bookable after cancel (service)" \
          "${BOOK_TESTS}::test_node_can_be_rebooked_after_cancel"
# "Refund cross-refs never leak to logs."
run_check "cancel does not leak refund refs to logs (service)" \
          "${BOOK_TESTS}::test_cancel_does_not_leak_refund_refs_to_logs"
# Party-size expansion keeps reconcile balanced (the I3 invariant under D3).
run_check "per-person node books + reconciles expanded (service)" \
          "${BOOK_TESTS}::test_per_person_node_books_and_reconciles_expanded_by_party_size"

# Gateway refund dispatch (unit, no DB).
run_check "FakeGateway refunds a settled charge (unit)" \
          "${PAY_TESTS}::test_fake_gateway_refund_settled_charge"
run_check "FakeGateway voids an unsettled charge (unit)" \
          "${PAY_TESTS}::test_fake_gateway_voids_unsettled_charge"
run_check "FakeGateway refund declines (unit)" \
          "${PAY_TESTS}::test_fake_gateway_refund_declines"

# HTTP contract: cancel 200 / 403 / 401 / 409.
run_check "POST /cancel returns the cancelled booking (router)" \
          "${BOOK_TESTS}::test_cancel_endpoint_200"
run_check "POST /cancel is advisor-only 403 (router)" \
          "${BOOK_TESTS}::test_cancel_endpoint_advisor_only_403"
run_check "POST /cancel requires a JWT 401 (router)" \
          "${BOOK_TESTS}::test_cancel_endpoint_requires_jwt"
run_check "POST /cancel maps a conflict to 409 (router)" \
          "${BOOK_TESTS}::test_cancel_endpoint_conflict_409"

# ── Static guards: surfaces are wired in ─────────────────────────────────────
guard "migration 0028 refund_status enum present" "${MIGRATION}" "create type public.refund_status"
guard "migration 0028 cancel columns present" "${MIGRATION}" "cancelled_at"
guard "one-live-booking is partial on cancel" "${MIGRATION}" "where cancelled_at is null"
guard "RefundStatus model present" "${INVOICE_MODEL}" "class RefundStatus"
guard "Booking refund columns present" "${MODEL_FILE}" "refund_status"
guard "gateway refund protocol present" "${GATEWAY_BASE}" "def refund"
guard "RefundResult normalized result present" "${GATEWAY_BASE}" "class RefundResult"
guard "Braintree refund/void dispatch present" "${GATEWAY_BT}" "_SETTLED_STATUSES"
guard "cancel_booking service present" "${SERVICE_FILE}" "async def cancel_booking"
guard "cancel endpoint registered" "${ROUTER_FILE}" "/cancel"
guard "api-client cancelBooking wrapper present" "${API_CLIENT}" "export async function cancelBooking"
guard "ovb SDK cancel_booking present" "${SDK_FILE}" "async def cancel_booking"
guard "ovb CLI cancel command present" "${CLI_CMD}" 'app.command("cancel")'
guard "web BookingPanel cancel wired" "${BOOKING_PANEL}" "cancelBooking"

# ── Redaction guard: refund cross-refs are never logged ──────────────────────
guard_absent "refund_gateway_ref is not a logged extra" "${SERVICE_FILE}" '"refund_gateway_ref":'

# ── Summary ──────────────────────────────────────────────────────────────────
log "─────────────────────────────────────────────"
log "Summary: ${PASSED} passed, ${FAILED} failed"
if (( FAILED > 0 )); then
  fail "${FAILED} acceptance bullet(s) failed."
fi
log "All cancel + refund (sR1) acceptance bullets passed."
exit 0
