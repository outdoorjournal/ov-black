#!/usr/bin/env bash
# scripts/verify-s06.sh — single-command slice verification for S06.
#
# Mirrors scripts/verify-s05.sh: one run_check per acceptance bullet, each
# invoking vitest with a -t filter so PASS/FAIL is bullet-granular rather
# than file-granular. A future agent reading CI output can localize a
# regression to a single invariant without opening the test file.
#
# Hard-fails (not skips) if pnpm is missing from PATH — S06's acceptance
# suite is JS-side (vitest + RTL + jsdom), so there is no graceful skip
# path. No pnpm, no verification.
#
# Environment:
#   None required. Assumes `apps/web` has already run `pnpm install` once
#   (run_check invokes `pnpm -C apps/web test -- --run ...`, which will
#   surface missing deps itself).
#
# Exit codes:
#   0   all acceptance bullets passed
#   1   any check failed or pnpm is not on PATH
#
# Output is structured and prefixed with [verify-s06] so the log greps clean.

set -euo pipefail

PREFIX="[verify-s06]"
REPO_ROOT="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." && pwd )"
WEB_DIR="${REPO_ROOT}/apps/web"
SUITE_FILE="s06-slice-acceptance"

log()  { printf '%s %s\n' "${PREFIX}" "$*"; }
warn() { printf '%s WARN: %s\n' "${PREFIX}" "$*" >&2; }
fail() { printf '%s FAIL: %s\n' "${PREFIX}" "$*" >&2; exit 1; }

require_cmd() {
  local cmd=$1
  command -v "${cmd}" >/dev/null 2>&1 || fail "required command not found on PATH: ${cmd}"
}

require_cmd pnpm

# ── Acceptance bullets — one per slice demo line ─────────────────────────────
# Each bullet maps to a single `test(...)` whose name starts with `(N)` in
# apps/web/tests/s06-slice-acceptance.test.tsx. We run them one at a time so
# the PASS/FAIL summary is bullet-granular.
PASSED=0
FAILED=0

# vitest's -t filter is treated as a regex, so the "(N)" prefix on each test
# name would be interpreted as a capture group and match the empty string —
# worse, a no-match run still exits 0 ("N skipped" is not a failure). We pick
# substrings from the body of each test name (post-"(N)") that are unique to
# that single bullet, then assert ">=1 passed" in the run's JSON output so a
# silent "0 ran" mismatch fails loudly rather than green-washing.
run_check() {
  local label=$1
  local name_filter=$2
  local tmp
  tmp="$(mktemp)"
  log "─────────────────────────────────────────────"
  log "Check: ${label}"
  if (
    cd "${WEB_DIR}" \
      && pnpm test -- --run --reporter=json --outputFile="${tmp}" "${SUITE_FILE}" -t "${name_filter}"
  ) >/dev/null 2>&1; then
    # Vitest JSON reporter writes numPassedTests / numFailedTests at top level.
    local passed failed
    passed=$(node -e "const fs=require('node:fs'); const r=JSON.parse(fs.readFileSync('${tmp}','utf8')); process.stdout.write(String(r.numPassedTests ?? 0));")
    failed=$(node -e "const fs=require('node:fs'); const r=JSON.parse(fs.readFileSync('${tmp}','utf8')); process.stdout.write(String(r.numFailedTests ?? 0));")
    if [[ "${failed}" == "0" && "${passed}" -ge 1 ]]; then
      PASSED=$((PASSED + 1))
      log "PASS: ${label} (${passed} test(s) ran)"
    else
      FAILED=$((FAILED + 1))
      warn "FAIL: ${label} (passed=${passed}, failed=${failed})"
    fi
  else
    FAILED=$((FAILED + 1))
    warn "FAIL: ${label} (vitest exited non-zero)"
  fi
  rm -f "${tmp}"
}

run_check "classifyMood maps Patagonia to glacial and Tuscany to amber" \
          "classifyMood maps Patagonia to glacial and Tuscany to amber"
run_check "ChatShell with Patagonia-seeded initialTurns applies data-mood glacial" \
          "ChatShell with Patagonia-seeded initialTurns applies data-mood glacial"
run_check "phase-shift gate: 1-turn renders fallback alpine, 3-turn renders amber" \
          "phase-shift gate: 1-turn renders fallback alpine, 3-turn renders amber"
run_check "conversation surface carries bg-paper across mood changes" \
          "conversation surface carries bg-paper across mood changes"
run_check "every MOODS entry satisfies WCAG AA contrast between palette fg and bg" \
          "every MOODS entry satisfies WCAG AA contrast"
run_check "AtmosFrame image onError hides image layer but keeps palette visible" \
          "AtmosFrame image onError hides image layer but keeps palette visible"

# ── Summary ──────────────────────────────────────────────────────────────────
log "────────────────────────────────────────────────"
log "Summary: ${PASSED} passed, ${FAILED} failed"

if (( FAILED > 0 )); then
  fail "${FAILED} acceptance bullet(s) failed."
fi

log "All S06 acceptance bullets passed."
exit 0
