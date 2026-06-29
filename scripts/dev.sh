#!/usr/bin/env bash
#
# dev.sh — launch the OV Black local stack (API + agent + web) in mprocs.
#
# Usage:
#   scripts/dev.sh            full stack: API + real local agent (:8080) + web
#   scripts/dev.sh --mock     AWS-free:   API (canned mock agent) + web only
#   scripts/dev.sh -h|--help
#
# Each service runs in its own mprocs pane with autorestart on, so a crash in
# one is relaunched automatically while the others keep running. See
# mprocs.yaml / mprocs.mock.yaml for the process definitions.
set -euo pipefail

usage() {
  sed -n '4,12p' "$0" | sed 's/^# \{0,1\}//'
}

# Resolve the repo root from this script's location so it runs from anywhere.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

MODE="real"
for arg in "$@"; do
  case "$arg" in
    --mock)      MODE="mock" ;;
    -h|--help)   usage; exit 0 ;;
    *) echo "dev.sh: unknown argument: $arg (try --help)" >&2; exit 2 ;;
  esac
done

# ── Preflight: mprocs must be installed ────────────────────────────────────
if ! command -v mprocs >/dev/null 2>&1; then
  echo "dev.sh: mprocs is not installed." >&2
  echo "        Install it with:  brew install mprocs" >&2
  exit 127
fi

# ── Preflight: local Supabase (DB + Auth + Studio + Mailpit) ───────────────
# The API needs Supabase in both modes (JWT validation, DB). It's a
# Docker-managed stack started by the supabase CLI, so we bring it up here
# rather than as an mprocs pane. Missing CLI / Docker is a warning, not a hard
# stop — the app panes still launch and the status pane shows Supabase down.
ensure_supabase() {
  if ! command -v supabase >/dev/null 2>&1; then
    echo "dev.sh: ⚠ supabase CLI not found — skipping local Supabase." >&2
    echo "        Install: brew install supabase/tap/supabase" >&2
    return 0
  fi
  if ! docker info >/dev/null 2>&1; then
    echo "dev.sh: ⚠ Docker isn't running — local Supabase can't start." >&2
    echo "        Start Docker Desktop and re-run (app panes still launch)." >&2
    return 0
  fi
  if supabase status >/dev/null 2>&1; then
    echo "dev.sh: Supabase already running (Studio :54323 · Mailpit :54324)."
  else
    echo "dev.sh: starting local Supabase (DB + Auth + Studio + Mailpit)…"
    supabase start || echo "dev.sh: ⚠ supabase start failed — see output above." >&2
  fi
}
ensure_supabase

if [[ "$MODE" == "mock" ]]; then
  echo "dev.sh: starting API + web (mock agent, no AWS)…"
  exec mprocs --config mprocs.mock.yaml
fi

# ── Preflight (real mode): the agent needs a live AWS SSO session ──────────
# The agent pane runs under AWS_PROFILE=tov-sso and needs Bedrock creds. Warn
# but don't block: autorestart means the agent pane recovers on its own once
# you run `aws sso login --profile tov-sso` in another terminal.
if command -v aws >/dev/null 2>&1; then
  if ! aws sts get-caller-identity --profile tov-sso >/dev/null 2>&1; then
    echo "dev.sh: ⚠ AWS profile 'tov-sso' has no active session." >&2
    echo "        The agent pane will fail to serve turns until you run:" >&2
    echo "          aws sso login --profile tov-sso" >&2
    echo "        (Or run 'scripts/dev.sh --mock' to skip the agent and AWS.)" >&2
  fi
fi

echo "dev.sh: starting API + agent + web…"
exec mprocs --config mprocs.yaml
