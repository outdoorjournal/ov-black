#!/usr/bin/env bash
# scripts/cleanup-staging-e2e.sh — delete the ephemeral e2e detritus that the
# staging e2e suite accumulates (one invited auth user + one client per test that
# calls POST /clients, via flows.unique_email → `e2e-<hex>@ovblack.dev`).
#
# Targets ONLY emails matching `e2e-%@ovblack.dev`. The two long-lived service
# identities (`ovb-e2e-advisor@…`, `ovb-e2e-traveler@…`) and the traveler-linked
# client are `ovb-e2e-*`, so they never match — they are preserved.
#
# Two stores, two channels (mirrors provision-staging-users.sh):
#   - clients + their graph: psql (the Data API/PostgREST is disabled). Because
#     itineraries.client_id is ON DELETE SET NULL (not cascade), itineraries are
#     deleted explicitly by client_id first (that cascades nodes/edges/analyses);
#     deleting the client then cascades dossiers/facts/contacts/sessions/etc.
#   - auth users: Supabase admin API (DELETE /auth/v1/admin/users/{id}).
#
# Secrets (service-role key, DB DSN) come from Secrets Manager and are never echoed.
#
# Usage:  scripts/cleanup-staging-e2e.sh            # delete
#         scripts/cleanup-staging-e2e.sh --dry-run  # count only, no deletes
set -euo pipefail

PREFIX="[cleanup-staging-e2e]"
log() { printf '%s %s\n' "$PREFIX" "$*" >&2; }
die() { printf '%s ERROR: %s\n' "$PREFIX" "$*" >&2; exit 1; }

DRY_RUN=0
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

export AWS_PROFILE="${AWS_PROFILE:-tov-sso}"
export AWS_REGION="${AWS_REGION:-us-east-2}"
for t in aws curl python3 psql; do command -v "$t" >/dev/null || die "$t not on PATH"; done

REPO_ROOT="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." && pwd )"
SUPABASE_URL="$(python3 -c "import json;print(json.load(open('$REPO_ROOT/infra/cdk/cdk.json'))['context']['ov-black:envs']['staging']['supabaseUrl'])")"

# Only-match pattern. Service identities are `ovb-e2e-*` → excluded by the `e2e-` anchor.
LIKE='e2e-%@ovblack.dev'

log "fetching secrets"
SK="$(aws secretsmanager get-secret-value --secret-id ov-black/staging/supabase-service-role --query SecretString --output text 2>/dev/null)" || die "service-role key unreadable (SSO expired?)"
DSN_RAW="$(aws secretsmanager get-secret-value --secret-id ov-black/staging/database-url --query SecretString --output text 2>/dev/null)" || die "database-url unreadable"
DB_DSN="${DSN_RAW/+asyncpg/}"

# ── 1. clients + their graphs (psql) ─────────────────────────────────────────
n_clients=$(psql "$DB_DSN" -tAc "select count(*) from public.clients where email like '$LIKE';")
n_itin=$(psql "$DB_DSN" -tAc "select count(*) from public.itineraries where client_id in (select id from public.clients where email like '$LIKE');")
log "ephemeral clients matching '$LIKE': $n_clients (with $n_itin itineraries)"
if [[ "$DRY_RUN" == 0 && "$n_clients" -gt 0 ]]; then
  psql "$DB_DSN" -v ON_ERROR_STOP=1 -q <<SQL
begin;
  delete from public.itineraries where client_id in (select id from public.clients where email like '$LIKE');
  delete from public.clients where email like '$LIKE';
commit;
SQL
  log "deleted $n_clients clients + $n_itin itineraries (graph cascaded)"
fi

# ── 2. ephemeral auth users (admin API) ──────────────────────────────────────
# bash 3.2 (macOS default) has no `mapfile`; stream ids through a while-read loop.
IDS="$(
  curl -sS "$SUPABASE_URL/auth/v1/admin/users?per_page=500" -H "apikey: $SK" -H "Authorization: Bearer $SK" \
  | python3 -c '
import json, re, sys
us = json.load(sys.stdin).get("users") or []
pat = re.compile(r"^e2e-.*@ovblack\.dev$", re.I)
for u in us:
    if pat.match(u.get("email") or ""):
        print(u["id"])'
)"
n_users=$(printf '%s\n' "$IDS" | grep -c . || true)
log "ephemeral auth users matching '$LIKE': $n_users"
if [[ "$DRY_RUN" == 0 && "$n_users" -gt 0 ]]; then
  deleted=0
  while IFS= read -r id; do
    [[ -n "$id" ]] || continue
    # --retry rides out transient resets; || true keeps `set -e` from aborting the
    # whole loop on one blip (the script is idempotent — re-run to mop up any misses).
    curl -sS --retry 3 --retry-connrefused -o /dev/null -X DELETE \
      "$SUPABASE_URL/auth/v1/admin/users/$id" -H "apikey: $SK" -H "Authorization: Bearer $SK" || true
    deleted=$((deleted+1))
  done <<< "$IDS"
  log "deleted $deleted auth users"
fi

if [[ "$DRY_RUN" == 1 ]]; then
  log "dry-run: nothing deleted."
else
  log "done. Preserved service identities (ovb-e2e-advisor / ovb-e2e-traveler) + their client."
fi
