#!/usr/bin/env bash
# scripts/verify-sI2.sh — single-command slice verification for M005/I2
# (Braintree payment, D025/D-PAY). See doc/mvp-plan.md §3 (M005).
#
# Runs the I2 acceptance bullets as pytest node ids and prints PASS/FAIL per
# bullet, then static guards that the payment surfaces are wired across
# api + gateway + SDKs + web + CDK. The DB-backed bullets self-skip without a
# local Supabase (127.0.0.1:54322) — run `supabase start` first.
#
# The unit/integration bullets use a Fake gateway and need NO Braintree
# credentials. A real sandbox pay-flow is an optional live probe: when
# BRAINTREE_MERCHANT_ID / BRAINTREE_PUBLIC_KEY / BRAINTREE_PRIVATE_KEY are set
# (and STAGING_API_URL points at a stack carrying them) the operator can drive
# `ovb invoices pay` by hand; this script does not require them.
#
# Environment:
#   None required. (Optional: STAGING_API_URL + sandbox keys for a live probe.)
#
# Exit codes:
#   0   all acceptance bullets passed (or skipped for lack of local DB)
#   1   any bullet failed
#
# Output is prefixed with [verify-sI2] so the log greps clean.

set -euo pipefail

PREFIX="[verify-sI2]"
REPO_ROOT="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." && pwd )"
API_DIR="${REPO_ROOT}/apps/api"
MIGRATION="${REPO_ROOT}/supabase/migrations/0024_payments.sql"
GATEWAY_BASE="${API_DIR}/app/payments/base.py"
GATEWAY_BT="${API_DIR}/app/payments/braintree_gateway.py"
SERVICE_FILE="${API_DIR}/app/services/payments.py"
ROUTER_FILE="${API_DIR}/app/routers/invoices.py"
CONFIG_FILE="${API_DIR}/app/config.py"
API_CLIENT="${REPO_ROOT}/packages/api-client/src/index.ts"
PAY_VIEW="${REPO_ROOT}/apps/web/app/invoices/[id]/_components/PayInvoiceView.tsx"
SECRETS_STACK="${REPO_ROOT}/infra/cdk/lib/secrets-stack.ts"
API_STACK="${REPO_ROOT}/infra/cdk/lib/api-stack.ts"
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

# ── Acceptance bullets ───────────────────────────────────────────────────────

# "Traveler pays an issued invoice; it flips to paid; a succeeded payment is
#  recorded with the cross-reference; the gateway gets reference + metadata."
run_check "pay settles, marks paid, records cross-ref (service)" \
          "${PAY_TESTS}::test_pay_settles_and_marks_paid"
# "a declined sale records a failed payment and leaves the invoice issued."
run_check "declined records failed, keeps issued (service)" \
          "${PAY_TESTS}::test_declined_records_failed_and_keeps_issued"
# "only an issued invoice is payable."
run_check "pay requires an issued invoice (service)" \
          "${PAY_TESTS}::test_pay_requires_issued"
# "an unconfigured gateway refuses (prod without keys)."
run_check "unconfigured gateway refuses (service)" \
          "${PAY_TESTS}::test_unconfigured_gateway_refuses"
# "redaction: no nonce / txn id / last-four leaks into logs."
run_check "no secrets leak to logs (service)" \
          "${PAY_TESTS}::test_pay_does_not_leak_secrets_to_logs"

# HTTP contract: pay 200, pay 401, payment-token 200.
run_check "POST /pay returns the paid invoice (router)" "${PAY_TESTS}::test_pay_endpoint_200"
run_check "POST /pay requires a JWT 401 (router)" "${PAY_TESTS}::test_pay_endpoint_requires_jwt"
run_check "POST /payment-token mints a token (router)" \
          "${PAY_TESTS}::test_payment_token_endpoint_200"

# Gateway-agnostic token helpers (no DB).
run_check "client token refuses when unconfigured (unit)" \
          "${PAY_TESTS}::test_generate_client_token_unconfigured"
run_check "fake gateway mints a token (unit)" "${PAY_TESTS}::test_fake_gateway_token"

# ── Static guards: surfaces are wired in ─────────────────────────────────────
guard "migration 0024 present" "${MIGRATION}" "create table if not exists public.payments"
guard "gateway-agnostic SaleResult contract" "${GATEWAY_BASE}" "class SaleResult"
guard "BraintreeGateway + FakeGateway present" "${GATEWAY_BT}" "class FakeGateway"
guard "pay_invoice service present" "${SERVICE_FILE}" "async def pay_invoice"
guard "cross-ref reference sent to gateway" "${SERVICE_FILE}" "new_gateway_reference"
guard "pay endpoint registered" "${ROUTER_FILE}" "/pay"
guard "payment-token endpoint registered" "${ROUTER_FILE}" "/payment-token"
guard "Braintree settings present" "${CONFIG_FILE}" "braintree_private_key"
guard "api-client payInvoice wrapper present" "${API_CLIENT}" "payInvoice"
guard "traveler PayInvoiceView present" "${PAY_VIEW}" "PayInvoiceView"
guard "CDK Braintree secret present" "${SECRETS_STACK}" "braintreeKeys"
guard "CDK injects Braintree keys" "${API_STACK}" "BRAINTREE_PRIVATE_KEY"

# ── Summary ──────────────────────────────────────────────────────────────────
log "─────────────────────────────────────────────"
log "Summary: ${PASSED} passed, ${FAILED} failed"
if (( FAILED > 0 )); then
  fail "${FAILED} acceptance bullet(s) failed."
fi
log "All I2 acceptance bullets passed."
exit 0
