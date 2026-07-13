#!/usr/bin/env bash
# scripts/mint-jwt.sh — mint a Supabase access_token (JWT) for an email.
#
# Usage:
#   scripts/mint-jwt.sh                                  # advisor JWT for git user.email, local
#   scripts/mint-jwt.sh --email me@x.com --role client
#   SUPABASE_URL=https://<proj>.supabase.co \
#     SUPABASE_SERVICE_ROLE_KEY=... scripts/mint-jwt.sh --email me@x.com    # staging
#
# Prints ONLY the JWT on stdout (everything else goes to stderr) so:
#   export OV_BLACK_STAGING_JWT="$(scripts/mint-jwt.sh --email me@x.com)"
#
# Diff vs. bootstrap-login.sh: that one prints a magic-link URL meant to be
# clicked in a browser. This one calls /auth/v1/verify server-side and emits
# the resulting access_token so curl/HTTP tools (and Claude) can use it.

set -euo pipefail

PREFIX="[mint-jwt]"
log() { printf '%s %s\n' "$PREFIX" "$*" >&2; }
die() { printf '%s ERROR: %s\n' "$PREFIX" "$*" >&2; exit 1; }

REPO_ROOT="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." && pwd )"

EMAIL=""
ROLE="advisor"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --email) EMAIL="${2:?}"; shift 2;;
    --role)  ROLE="${2:?}";  shift 2;;
    -h|--help) sed -n '2,15p' "$0"; exit 0;;
    *) die "unknown flag: $1";;
  esac
done

[[ -n "$EMAIL" ]] || EMAIL="$(git config --get user.email || true)"
[[ -n "$EMAIL" ]] || die "--email not given and git user.email is unset"
[[ "$ROLE" == "advisor" || "$ROLE" == "client" ]] || die "--role must be advisor|client"

SUPABASE_URL="${SUPABASE_URL:-http://127.0.0.1:54321}"
if [[ -z "${SUPABASE_SERVICE_ROLE_KEY:-}" ]]; then
  env_file="${REPO_ROOT}/apps/api/.env"
  [[ -f "$env_file" ]] || die "SUPABASE_SERVICE_ROLE_KEY unset and $env_file missing"
  SUPABASE_SERVICE_ROLE_KEY=$(grep -E '^supabase_service_role_key=' "$env_file" | cut -d= -f2- || true)
  [[ -n "$SUPABASE_SERVICE_ROLE_KEY" ]] || die "supabase_service_role_key missing from $env_file"
fi

admin() {
  local method="$1" path="$2" body="${3:-}"
  if [[ -n "$body" ]]; then
    curl -sS -X "$method" "$SUPABASE_URL$path" \
      -H "apikey: $SUPABASE_SERVICE_ROLE_KEY" \
      -H "Authorization: Bearer $SUPABASE_SERVICE_ROLE_KEY" \
      -H 'content-type: application/json' -d "$body"
  else
    curl -sS -X "$method" "$SUPABASE_URL$path" \
      -H "apikey: $SUPABASE_SERVICE_ROLE_KEY" \
      -H "Authorization: Bearer $SUPABASE_SERVICE_ROLE_KEY"
  fi
}

curl -sf -o /dev/null "$SUPABASE_URL/auth/v1/settings" \
  -H "apikey: $SUPABASE_SERVICE_ROLE_KEY" \
  || die "Supabase Auth not reachable at $SUPABASE_URL"

# 1. ensure user exists (idempotent — same shape as bootstrap-login.sh)
log "ensuring auth user for $EMAIL"
# URL-encode the email for the ?filter= query: a plus-addressed mailbox
# (chris+tag@…) would otherwise have its '+' decoded as a space, so the lookup
# misses the existing user and the create below 409s ("failed to create").
EMAIL_Q=$(python3 -c 'import sys,urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$EMAIL")
users=$(admin GET "/auth/v1/admin/users?filter=$EMAIL_Q")
uid=$(printf '%s' "$users" | python3 -c '
import json,sys
d=json.load(sys.stdin); us=d.get("users") or []
for u in us:
  if u.get("email","").lower()==sys.argv[1].lower(): print(u["id"]); break' "$EMAIL")
if [[ -z "$uid" ]]; then
  body=$(python3 -c 'import json,sys;print(json.dumps({"email":sys.argv[1],"email_confirm":True}))' "$EMAIL")
  uid=$(admin POST "/auth/v1/admin/users" "$body" \
    | python3 -c 'import json,sys;print(json.load(sys.stdin).get("id",""))')
  [[ -n "$uid" ]] || die "failed to create auth user"
fi

# 2. ensure profiles row with role (local only — staging seed is managed elsewhere)
if [[ "$SUPABASE_URL" == "http://127.0.0.1:54321" ]]; then
  log "ensuring profiles row id=$uid role=$ROLE"
  DB_URL="${DB_URL:-postgresql://postgres:postgres@127.0.0.1:54322/postgres}"
  if command -v psql >/dev/null; then
    psql "$DB_URL" -v ON_ERROR_STOP=1 -q -c \
      "insert into public.profiles (id,role) values ('$uid','$ROLE')
       on conflict (id) do update set role=excluded.role;"
  fi
fi

# 3. mint magic link → 4. verify it → access_token
log "minting + verifying magic link"
link_body=$(python3 -c 'import json,sys;print(json.dumps({"type":"magiclink","email":sys.argv[1]}))' "$EMAIL")
hashed=$(admin POST "/auth/v1/admin/generate_link" "$link_body" | python3 -c '
import json,sys
d=json.load(sys.stdin); p=d.get("properties") or {}
print(p.get("hashed_token") or d.get("hashed_token") or "")')
[[ -n "$hashed" ]] || die "no hashed_token returned"

verify_body=$(python3 -c 'import json,sys;print(json.dumps({"type":"magiclink","token_hash":sys.argv[1]}))' "$hashed")
token=$(curl -sS -X POST "$SUPABASE_URL/auth/v1/verify" \
  -H "apikey: $SUPABASE_SERVICE_ROLE_KEY" -H 'content-type: application/json' \
  -d "$verify_body" \
  | python3 -c 'import json,sys;print(json.load(sys.stdin).get("access_token",""))')
[[ -n "$token" ]] || die "verify did not return access_token"

log "minted JWT (ttl ~1h) for $EMAIL ($ROLE)"
printf '%s\n' "$token"
