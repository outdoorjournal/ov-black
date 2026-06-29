#!/usr/bin/env bash
#
# dev-status.sh — live dashboard of the OV Black local stack: URLs + health.
#
# Runs as the "status" pane in mprocs (see mprocs.yaml) and refreshes every few
# seconds so you can always see what's up and which URL to open. Also runnable
# standalone:
#
#   scripts/dev-status.sh           # full stack
#   scripts/dev-status.sh --mock    # omit the agent row (mock-agent mode)
set -u

MOCK=0
[[ "${1:-}" == "--mock" ]] && MOCK=1

# up == curl gets any 2xx/3xx within the timeout
http_up() {
  local code
  code=$(curl -s -o /dev/null -m 1 -w "%{http_code}" "$1" 2>/dev/null || echo 000)
  [[ "$code" =~ ^[23] ]]
}
tcp_up() { nc -z -w 1 "$1" "$2" >/dev/null 2>&1; }

# row LABEL URL EXIT_STATUS  (0 == up)
row() {
  local mark
  if [[ "$3" == 0 ]]; then mark=$'\033[32m● up  \033[0m'; else mark=$'\033[31m○ down\033[0m'; fi
  printf "  %b  %-8s %s\n" "$mark" "$1" "$2"
}

while true; do
  printf '\033[2J\033[H'   # clear screen + cursor home
  echo "OV Black — local stack (refreshes every 5s · Ctrl-C / mprocs 'x' to stop)"
  echo
  echo "App"
  http_up http://localhost:3000        ; row "web"   "http://localhost:3000  ← the app" $?
  http_up http://localhost:8000/health ; row "api"   "http://localhost:8000/docs" $?
  if [[ "$MOCK" == 0 ]]; then
    http_up http://localhost:8080/ping ; row "agent" "http://localhost:8080 (POST /invocations)" $?
  fi
  echo
  echo "Supabase (local)"
  http_up http://127.0.0.1:54321/auth/v1/health ; row "api"     "http://127.0.0.1:54321" $?
  http_up http://127.0.0.1:54323                ; row "studio"  "http://127.0.0.1:54323" $?
  http_up http://127.0.0.1:54324/livez          ; row "mailpit" "http://127.0.0.1:54324  ← magic-link emails" $?
  tcp_up  127.0.0.1 54322                        ; row "db"      "postgresql://postgres:postgres@127.0.0.1:54322/postgres" $?
  sleep 5
done
