#!/usr/bin/env bash
#
# stop-dev.sh — stop everything scripts/dev.sh runs: mprocs plus the API
# (:8000), agent (:8080), web (:3000), and mock-agent API (:8011), whether
# they're under mprocs or were started standalone. Supabase containers are
# left up — dev.sh reuses them as a preflight (pass --supabase to stop them
# too).
#
# Kill order matters: mprocs goes first, otherwise its `autorestart: true`
# panes resurrect whatever is killed underneath it. Only mprocs instances
# whose cwd is this repo are touched. Port listeners are killed together
# with their wrapper parents (`uv run`, `next dev`) so nothing respawns or
# keeps a port bound.
#
# Usage:
#   scripts/stop-dev.sh              # stop the app stack, keep Supabase
#   scripts/stop-dev.sh --supabase   # also run `supabase stop`
#
# Exit 0 once all four ports are free; non-zero if something survived.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORTS=(3000 8000 8080 8011)
WITH_SUPABASE=0

case "${1:-}" in
  -h|--help) sed -n '3,19p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
  --supabase) WITH_SUPABASE=1 ;;
  "") ;;
  *) echo "stop-dev: unknown argument: $1 (try --help)" >&2; exit 2 ;;
esac

# ── 1. mprocs first, and only instances rooted in this repo ─────────────────
for pid in $(pgrep -x mprocs 2>/dev/null || true); do
  cwd="$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p')"
  if [[ "$cwd" == "$ROOT"* ]]; then
    echo "stop-dev: stopping mprocs (pid ${pid})…"
    kill "$pid" 2>/dev/null || true
    for _ in $(seq 1 20); do kill -0 "$pid" 2>/dev/null || break; sleep 0.25; done
    kill -9 "$pid" 2>/dev/null || true
  fi
done

# ── 2. Port listeners + their wrapper parents ────────────────────────────────
# `uv run …` and the `next dev` bin spawn the child that actually holds the
# port; both ends have to go or the parent lingers (or respawns the child).
pids=()
for port in "${PORTS[@]}"; do
  for pid in $(lsof -ti "tcp:${port}" -sTCP:LISTEN 2>/dev/null || true); do
    pids+=("$pid")
    ppid="$(ps -o ppid= -p "$pid" 2>/dev/null | tr -d ' ')"
    if [[ -n "${ppid}" && "${ppid}" != 1 ]]; then
      pcmd="$(ps -o command= -p "$ppid" 2>/dev/null || true)"
      case "$pcmd" in
        *"uv run"*|*"next dev"*|*uvicorn*|*"python -m agent"*) pids+=("$ppid") ;;
      esac
    fi
  done
done

if [[ ${#pids[@]} -eq 0 ]]; then
  echo "stop-dev: nothing listening on ports ${PORTS[*]}."
else
  read -ra pids <<<"$(printf '%s\n' "${pids[@]}" | sort -un | tr '\n' ' ')"
  echo "stop-dev: stopping pids: ${pids[*]}"
  kill "${pids[@]}" 2>/dev/null || true
  for _ in $(seq 1 20); do
    alive=0
    for pid in "${pids[@]}"; do kill -0 "$pid" 2>/dev/null && alive=1 && break; done
    [[ ${alive} -eq 0 ]] && break
    sleep 0.25
  done
  for pid in "${pids[@]}"; do
    if kill -0 "$pid" 2>/dev/null; then
      echo "stop-dev: pid ${pid} still up — sending SIGKILL."
      kill -9 "$pid" 2>/dev/null || true
    fi
  done
fi

if [[ ${WITH_SUPABASE} -eq 1 ]]; then
  echo "stop-dev: stopping Supabase…"
  (cd "$ROOT" && supabase stop)
fi

# ── 3. Verify ────────────────────────────────────────────────────────────────
leftover="$(lsof -nP -sTCP:LISTEN $(printf -- '-iTCP:%s ' "${PORTS[@]}") 2>/dev/null || true)"
if [[ -n "${leftover}" ]]; then
  echo "stop-dev: something is still listening ✗" >&2
  echo "${leftover}" >&2
  exit 1
fi
echo "stop-dev: ports ${PORTS[*]} free ✔"
