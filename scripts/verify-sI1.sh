#!/usr/bin/env bash
# scripts/verify-sI1.sh — single-command slice verification for M005/I1
# (Invoices + line-item ledger). See doc/mvp-plan.md §3 (M005).
#
# Runs the I1 acceptance bullets as pytest node ids and prints PASS/FAIL per
# bullet, then static guards that the invoice surfaces are wired across
# api + SDKs + web + CLI. The DB-backed bullets self-skip without a local
# Supabase (127.0.0.1:54322) — run `supabase start` first to exercise them.
#
# Environment:
#   None required.
#
# Exit codes:
#   0   all acceptance bullets passed (or skipped for lack of local DB)
#   1   any bullet failed
#
# Output is prefixed with [verify-sI1] so the log greps clean.

set -euo pipefail

PREFIX="[verify-sI1]"
REPO_ROOT="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." && pwd )"
API_DIR="${REPO_ROOT}/apps/api"
MIGRATION="${REPO_ROOT}/supabase/migrations/0023_invoices.sql"
MODEL_FILE="${API_DIR}/app/models/invoice.py"
SERVICE_FILE="${API_DIR}/app/services/invoices.py"
ROUTER_FILE="${API_DIR}/app/routers/invoices.py"
API_CLIENT="${REPO_ROOT}/packages/api-client/src/index.ts"
INVOICE_PANEL="${REPO_ROOT}/apps/web/app/_components/itinerary-graph/views/horizontal/InvoicePanel.tsx"
HORIZ_VIEW="${REPO_ROOT}/apps/web/app/_components/itinerary-graph/views/horizontal/HorizontalView.tsx"
CLI_CMD="${REPO_ROOT}/apps/cli/src/ovb/cli/commands/invoices.py"
INV_TESTS="tests/test_invoices.py"

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

# "Advisor assembles an invoice; charge-from-node + signed discount/adjustment;
#  total = Σ signed lines; a void appends a reversal that nets it back."
run_check "signed ledger totals + journal-entry void (service)" \
          "${INV_TESTS}::test_signed_ledger_totals_and_void"
# "each line's currency must match its invoice."
run_check "currency mismatch rejected (service)" \
          "${INV_TESTS}::test_currency_mismatch_rejected"
# "charge-from-node requires the node to carry a cost (B4)."
run_check "node without cost rejected (service)" \
          "${INV_TESTS}::test_node_without_cost_rejected"
# "draft assembles freely; issued is append-only; issue needs a line; void closes."
run_check "issue / append-only / void lifecycle gates (service)" \
          "${INV_TESTS}::test_issue_lifecycle_gates"
run_check "draft hard-delete + per-itinerary listing (service)" \
          "${INV_TESTS}::test_draft_delete_and_list"

# HTTP contract: create 201 / advisor-only 403 / 401; read gate (owner+advisor).
run_check "POST create invoice 201 (router)" "${INV_TESTS}::test_create_invoice_endpoint_201"
run_check "create is advisor-only 403 (router)" \
          "${INV_TESTS}::test_create_invoice_endpoint_advisor_only_403"
run_check "create requires a JWT 401 (router)" \
          "${INV_TESTS}::test_create_invoice_endpoint_requires_jwt"
run_check "GET invoice admits advisor (router)" \
          "${INV_TESTS}::test_get_invoice_endpoint_200_for_advisor"
run_check "GET invoice forbids a stranger 403 (router)" \
          "${INV_TESTS}::test_get_invoice_endpoint_forbidden_for_stranger"

# ── Static guards: surfaces are wired in ─────────────────────────────────────
guard "migration 0023 present" "${MIGRATION}" "invoice_line_kind"
guard "Invoice + line models present" "${MODEL_FILE}" "class InvoiceLineItem"
guard "create/issue/void service present" "${SERVICE_FILE}" "async def issue_invoice"
guard "journal-entry void service present" "${SERVICE_FILE}" "async def void_line_item"
guard "create invoice endpoint registered" "${ROUTER_FILE}" '"/itinerary/{itinerary_id}/invoices"'
guard "void-line endpoint registered" "${ROUTER_FILE}" "/void"
guard "api-client invoice wrappers present" "${API_CLIENT}" "addInvoiceLineItem"
guard "InvoicePanel present" "${INVOICE_PANEL}" "InvoicePanel"
guard "Invoices tab wired in the canvas" "${HORIZ_VIEW}" "InvoicePanel"
guard "ovb invoices CLI group present" "${CLI_CMD}" "add-line"

# ── Summary ──────────────────────────────────────────────────────────────────
log "─────────────────────────────────────────────"
log "Summary: ${PASSED} passed, ${FAILED} failed"
if (( FAILED > 0 )); then
  fail "${FAILED} acceptance bullet(s) failed."
fi
log "All I1 acceptance bullets passed."
exit 0
