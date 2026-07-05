#!/usr/bin/env bash
#
# restart-agent.sh — restart the local concierge agent on :8080 so it picks up
# code changes.
#
# Why this exists: the agent pane runs `uv run python -m agent` WITHOUT --reload
# (unlike the API and web, which hot-reload themselves). So after editing
# anything under apps/agent — a prompt, a tool, the turn loop — the running
# agent keeps serving the OLD code until it is restarted. This script is the
# one-command restart, safe to run from anywhere and safe to script (the e2e
# harness and Claude use it to get a clean agent before a live turn).
#
# Two worlds, detected automatically:
#   • Stack under mprocs (scripts/dev.sh — the normal case): we stop the agent
#     process and mprocs' `autorestart: true` relaunches it with the pane's env.
#     We only have to wait for it to come back healthy.
#   • Agent running standalone (no mprocs): we start a fresh detached process
#     ourselves, using the same command + env mprocs.yaml uses, logging to a file.
#
# Usage:
#   scripts/restart-agent.sh          # restart and wait until healthy
#   scripts/restart-agent.sh -h
#
# Exit 0 once http://localhost:8080/ping answers; non-zero if it never does.
set -euo pipefail

case "${1:-}" in
  -h|--help) sed -n '4,26p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
  "") ;;
  *) echo "restart-agent: unknown argument: $1 (try --help)" >&2; exit 2 ;;
esac

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AGENT_PORT=8080
PING="http://localhost:${AGENT_PORT}/ping"
LOG="${TMPDIR:-/tmp}/ovb-agent.log"

# The PID of whatever is LISTENing on the agent port (empty if nothing is).
agent_pid() { lsof -ti "tcp:${AGENT_PORT}" -sTCP:LISTEN 2>/dev/null | head -1; }
mprocs_running() { pgrep -x mprocs >/dev/null 2>&1; }

# Poll /ping for up to ~30s. mprocs autorestart + `uv run` startup is a couple
# of seconds; a standalone cold start with a uv sync can be a little longer.
wait_healthy() {
  for _ in $(seq 1 60); do
    if curl -fsS -o /dev/null -m 1 "$PING" 2>/dev/null; then return 0; fi
    sleep 0.5
  done
  return 1
}

# ── Stop the current agent (target the captured PID only, never "whatever holds
# the port" — mprocs can rebind the port within a second, and we must not kill
# the replacement). ─────────────────────────────────────────────────────────
pid="$(agent_pid || true)"
if [[ -n "${pid}" ]]; then
  echo "restart-agent: stopping agent (pid ${pid}) on :${AGENT_PORT}…"
  kill "${pid}" 2>/dev/null || true
  for _ in $(seq 1 20); do kill -0 "${pid}" 2>/dev/null || break; sleep 0.25; done
  if kill -0 "${pid}" 2>/dev/null; then
    echo "restart-agent: still up — sending SIGKILL to ${pid}."
    kill -9 "${pid}" 2>/dev/null || true
  fi
else
  echo "restart-agent: no agent currently listening on :${AGENT_PORT}."
fi

# ── Bring a fresh one up ──────────────────────────────────────────────────────
if mprocs_running; then
  echo "restart-agent: mprocs is managing the agent — waiting for autorestart…"
else
  echo "restart-agent: mprocs not running — starting a standalone agent…"
  ( cd "${ROOT}/apps/agent" \
    && AWS_PROFILE="${AWS_PROFILE:-tov-sso}" \
       AWS_REGION="${AWS_REGION:-us-west-2}" \
       BACKEND_BASE_URL="${BACKEND_BASE_URL:-http://localhost:8000}" \
       nohup uv run python -m agent >"${LOG}" 2>&1 & )
  echo "restart-agent: logs → ${LOG}"
fi

if wait_healthy; then
  echo "restart-agent: agent healthy on :${AGENT_PORT} ✔  (pid $(agent_pid))"
else
  echo "restart-agent: agent did NOT come healthy on :${AGENT_PORT} ✗" >&2
  if mprocs_running; then
    echo "  Check the mprocs 'agent' pane — likely a crash loop. Common cause:" >&2
    echo "  no AWS SSO session. Run: aws sso login --profile tov-sso" >&2
  else
    echo "  Inspect the standalone log: tail -f ${LOG}" >&2
  fi
  exit 1
fi
