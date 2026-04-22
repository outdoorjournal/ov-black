#!/usr/bin/env bash
# scripts/bootstrap-login.sh — local-dev login bootstrap.
#
# Creates (or reuses) an auth user for a given email, ensures a profiles row
# with the requested role, mints a magic link via the Supabase admin API, and
# prints the link. Click it in your browser to land logged-in on the web app.
#
# We go around POST /auth/redeem-invite on purpose: local Supabase ships with
# no SMTP wired up, so the admin/generate_link call made by the redeem path
# just returns a link the server swallows. For a local bootstrap we want the
# link on stdout, not in a mailbox that never receives mail.
#
# Usage:
#   scripts/bootstrap-login.sh [--email EMAIL] [--role advisor|client]
#
# Defaults:
#   --email  $(git config user.email)
#   --role   advisor
#
# Env overrides:
#   DB_URL              postgres dsn (default: local Supabase on :54322)
#   SUPABASE_URL        Supabase project URL (default: http://127.0.0.1:54321)
#   SUPABASE_SERVICE_ROLE_KEY  admin key. If unset, read from apps/api/.env.
#   WEB_ORIGIN          redirect target after magic-link verification
#                       (default: http://localhost:3000)
#   SUPABASE_CONTAINER  db container to exec into if no local psql is found
#                       (default: supabase_db_ov-black)
#
# Precondition: `supabase start` is up.

set -euo pipefail

PREFIX="[bootstrap-login]"
log()  { printf '%s %s\n'       "$PREFIX" "$*"; }
die()  { printf '%s ERROR: %s\n' "$PREFIX" "$*" >&2; exit 1; }

REPO_ROOT="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." && pwd )"

EMAIL=""
ROLE="advisor"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --email) EMAIL="${2:?}"; shift 2;;
    --role)  ROLE="${2:?}";  shift 2;;
    -h|--help) sed -n '2,33p' "$0"; exit 0;;
    *) die "unknown flag: $1";;
  esac
done

if [[ -z "$EMAIL" ]]; then
  EMAIL="$(git config --get user.email || true)"
  [[ -n "$EMAIL" ]] || die "--email not provided and git user.email is unset"
fi
[[ "$ROLE" == "advisor" || "$ROLE" == "client" ]] \
  || die "--role must be 'advisor' or 'client', got: $ROLE"
[[ "$EMAIL" =~ ^[A-Za-z0-9._+-]+@[A-Za-z0-9.-]+$ ]] \
  || die "invalid email: $EMAIL"

DB_URL="${DB_URL:-postgresql://postgres:postgres@127.0.0.1:54322/postgres}"
SUPABASE_URL="${SUPABASE_URL:-http://127.0.0.1:54321}"
WEB_ORIGIN="${WEB_ORIGIN:-http://localhost:3000}"
SUPABASE_CONTAINER="${SUPABASE_CONTAINER:-supabase_db_ov-black}"

if [[ -z "${SUPABASE_SERVICE_ROLE_KEY:-}" ]]; then
  env_file="${REPO_ROOT}/apps/api/.env"
  [[ -f "$env_file" ]] || die "SUPABASE_SERVICE_ROLE_KEY unset and $env_file not found"
  SUPABASE_SERVICE_ROLE_KEY=$(grep -E '^supabase_service_role_key=' "$env_file" | cut -d= -f2- || true)
  [[ -n "$SUPABASE_SERVICE_ROLE_KEY" ]] \
    || die "supabase_service_role_key not set in $env_file"
fi

# --- psql: prefer host, fall back to docker exec into the supabase_db container
if command -v psql >/dev/null 2>&1; then
  psql_exec() { psql "$DB_URL" -v ON_ERROR_STOP=1 -q "$@"; }
else
  command -v docker >/dev/null 2>&1 \
    || die "no local psql and docker not installed — install one"
  docker exec "$SUPABASE_CONTAINER" true >/dev/null 2>&1 \
    || die "supabase db container '$SUPABASE_CONTAINER' is not running (is \`supabase start\` up?)"
  psql_exec() { docker exec -i "$SUPABASE_CONTAINER" \
    psql -U postgres -d postgres -v ON_ERROR_STOP=1 -q "$@"; }
fi

admin_curl() {
  # $1 = method, $2 = path, $3 (optional) = JSON body
  local method="$1" path="$2" body="${3:-}"
  if [[ -n "$body" ]]; then
    curl -sS -X "$method" "$SUPABASE_URL$path" \
      -H "apikey: $SUPABASE_SERVICE_ROLE_KEY" \
      -H "Authorization: Bearer $SUPABASE_SERVICE_ROLE_KEY" \
      -H 'content-type: application/json' \
      -d "$body"
  else
    curl -sS -X "$method" "$SUPABASE_URL$path" \
      -H "apikey: $SUPABASE_SERVICE_ROLE_KEY" \
      -H "Authorization: Bearer $SUPABASE_SERVICE_ROLE_KEY"
  fi
}

json_get() { python3 -c "import json,sys;print(json.load(sys.stdin).get(sys.argv[1], ''))" "$1"; }
json_build() { python3 -c 'import json,sys;print(json.dumps(dict(zip(sys.argv[1::2], sys.argv[2::2]))))' "$@"; }

# --- sanity
curl -sf -o /dev/null "$SUPABASE_URL/auth/v1/settings" \
  || die "Supabase Auth not reachable at $SUPABASE_URL (is \`supabase start\` up?)"

# --- 1. ensure auth user exists (admin API; idempotent via email lookup)
log "looking up auth user for $EMAIL"
users_json=$(admin_curl GET "/auth/v1/admin/users?filter=$EMAIL")
user_id=$(printf '%s' "$users_json" \
  | python3 -c 'import json,sys
d=json.load(sys.stdin); users=d.get("users") or []
for u in users:
  if u.get("email","").lower()==sys.argv[1].lower():
    print(u["id"]); break' "$EMAIL")

if [[ -z "$user_id" ]]; then
  log "creating auth user (email_confirm=true)"
  create_body=$(python3 -c 'import json,sys;print(json.dumps({"email":sys.argv[1],"email_confirm":True}))' "$EMAIL")
  created=$(admin_curl POST "/auth/v1/admin/users" "$create_body")
  user_id=$(printf '%s' "$created" | json_get id)
  [[ -n "$user_id" ]] || die "failed to create auth user: $created"
fi
log "auth user id: $user_id"

# --- 2. ensure a profiles row with the requested role
log "ensuring profiles row: id=$user_id role=$ROLE"
psql_exec -c "insert into public.profiles (id, role)
  values ('$user_id', '$ROLE')
  on conflict (id) do update set role = excluded.role;"

# --- 3. mint a magic link via admin/generate_link
#
# We don't hand the user the default `action_link` (which routes through
# /auth/v1/verify and redirects to redirect_to) because Supabase's local
# config only allow-lists site_url — any /auth/callback suffix gets stripped
# and the PKCE code never reaches the web app. Instead we build our own URL
# straight to /auth/callback with the hashed_token + type, which the web
# route handler verifies via supabase.auth.verifyOtp.
log "minting magic link (type=magiclink)"
link_body=$(python3 -c 'import json,sys;print(json.dumps({"type":"magiclink","email":sys.argv[1]}))' "$EMAIL")
link_resp=$(admin_curl POST "/auth/v1/admin/generate_link" "$link_body")
hashed_token=$(printf '%s' "$link_resp" | python3 -c '
import json,sys
d=json.load(sys.stdin)
p=d.get("properties") or {}
print(p.get("hashed_token") or d.get("hashed_token") or "")')

[[ -n "$hashed_token" ]] \
  || die "admin/generate_link returned no hashed_token: $link_resp"

callback_url="$WEB_ORIGIN/auth/callback?token_hash=$hashed_token&type=magiclink"

log "success — click this link in a browser to log in:"
printf '\n%s\n\n' "$callback_url"
