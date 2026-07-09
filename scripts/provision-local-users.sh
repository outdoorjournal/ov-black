#!/usr/bin/env bash
# scripts/provision-local-users.sh — (re)provision the local password-grant
# service users that the e2e suite + `ovb --profile local-advisor|local-traveler`
# rely on. A fresh `supabase start` (or `supabase db reset`) wipes auth users, so
# the dedicated `local-advisor` / `local-traveler` accounts must be recreated;
# this is the script the CLAUDE.md "created per dev machine" note implies.
#
# What it does (idempotent):
#   1. Reads each profile's email/password/role/anon_key from the gitignored
#      ~/.ovblack/.cli (no secrets are committed or printed).
#   2. Ensures a confirmed Supabase auth user with that password (admin API) and a
#      public.profiles row carrying the app role (advisor | client).
#   3. Ensures a `clients` row owned by local-advisor whose email is the traveler's,
#      then hits GET /me/client as the traveler to backfill the auth_user_id link
#      so chat-as-traveler + /me/* resolve.
#
# Prereqs: local Supabase up (`supabase start`), the API up on :8000, psql on PATH.
#
# Usage:  scripts/provision-local-users.sh
set -euo pipefail

PREFIX="[provision-local-users]"
log() { printf '%s %s\n' "$PREFIX" "$*" >&2; }
die() { printf '%s ERROR: %s\n' "$PREFIX" "$*" >&2; exit 1; }

REPO_ROOT="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." && pwd )"
SUPABASE_URL="${SUPABASE_URL:-http://127.0.0.1:54321}"
DB_URL="${DB_URL:-postgresql://postgres:postgres@127.0.0.1:54322/postgres}"
API_URL="${API_URL:-http://127.0.0.1:8000}"
CLI="${OVB_CONFIG:-$HOME/.ovblack/.cli}"

[[ -f "$CLI" ]] || die ".cli not found at $CLI (set OVB_CONFIG)"
command -v psql >/dev/null || die "psql not on PATH"
SK=$(grep -E '^supabase_service_role_key=' "$REPO_ROOT/apps/api/.env" | cut -d= -f2- || true)
[[ -n "$SK" ]] || die "supabase_service_role_key missing from apps/api/.env"
curl -sf -o /dev/null "$SUPABASE_URL/auth/v1/settings" || die "Supabase Auth unreachable at $SUPABASE_URL"
curl -sf -o /dev/null "$API_URL/health" || die "API unreachable at $API_URL (start it on :8000)"

cli_get() {  # cli_get <profile> <key>
  python3 - "$CLI" "$1" "$2" <<'PY'
import configparser, sys
c = configparser.ConfigParser()
c.read(sys.argv[1])
print(c.get(f"profile {sys.argv[2]}", sys.argv[3], fallback=""))
PY
}

admin() {  # admin <METHOD> <PATH> [JSON_BODY]
  local m="$1" p="$2" b="${3:-}"
  if [[ -n "$b" ]]; then
    curl -sS -X "$m" "$SUPABASE_URL$p" -H "apikey: $SK" -H "Authorization: Bearer $SK" \
      -H 'content-type: application/json' -d "$b"
  else
    curl -sS -X "$m" "$SUPABASE_URL$p" -H "apikey: $SK" -H "Authorization: Bearer $SK"
  fi
}

# App role enum is {advisor, client}; the .cli calls the invitee role "traveler".
app_role() { [[ "$1" == "traveler" || "$1" == "client" ]] && echo client || echo advisor; }

ensure_user() {  # ensure_user <email> <app_role> <password> -> prints uid
  local email="$1" role="$2" pw="$3" users uid body
  users=$(admin GET "/auth/v1/admin/users?filter=$email")
  uid=$(printf '%s' "$users" | python3 -c '
import json, sys
us = json.load(sys.stdin).get("users") or []
print(next((u["id"] for u in us if u.get("email","").lower()==sys.argv[1].lower()), ""))' "$email")
  body=$(python3 -c 'import json,sys; print(json.dumps({"email":sys.argv[1],"password":sys.argv[2],"email_confirm":True}))' "$email" "$pw")
  if [[ -z "$uid" ]]; then
    uid=$(admin POST "/auth/v1/admin/users" "$body" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("id",""))')
    [[ -n "$uid" ]] || die "failed to create auth user $email"
    log "created auth user $email ($role)"
  else
    admin PUT "/auth/v1/admin/users/$uid" "$body" >/dev/null
    log "updated password for $email ($role)"
  fi
  psql "$DB_URL" -v ON_ERROR_STOP=1 -q -c \
    "insert into public.profiles (id, role) values ('$uid', '$role')
     on conflict (id) do update set role = excluded.role;"
  printf '%s' "$uid"
}

grant() {  # grant <email> <password> <anon_key> -> prints access_token
  curl -sS -X POST "$SUPABASE_URL/auth/v1/token?grant_type=password" \
    -H "apikey: $3" -H 'content-type: application/json' \
    -d "$(python3 -c 'import json,sys; print(json.dumps({"email":sys.argv[1],"password":sys.argv[2]}))' "$1" "$2")" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin).get("access_token",""))'
}

ADV_EMAIL=$(cli_get local-advisor email);   ADV_PW=$(cli_get local-advisor password);   ADV_ANON=$(cli_get local-advisor anon_key)
TRV_EMAIL=$(cli_get local-traveler email);  TRV_PW=$(cli_get local-traveler password);  TRV_ANON=$(cli_get local-traveler anon_key)
ADV_ROLE=$(app_role "$(cli_get local-advisor role)")
TRV_ROLE=$(app_role "$(cli_get local-traveler role)")
[[ -n "$ADV_EMAIL" && -n "$ADV_PW" ]] || die "local-advisor email/password missing from $CLI"
[[ -n "$TRV_EMAIL" && -n "$TRV_PW" ]] || die "local-traveler email/password missing from $CLI"

ensure_user "$ADV_EMAIL" "$ADV_ROLE" "$ADV_PW" >/dev/null

ADV_JWT=$(grant "$ADV_EMAIL" "$ADV_PW" "$ADV_ANON")
[[ -n "$ADV_JWT" ]] || die "advisor password grant failed (check local-advisor anon_key/password)"

# Ensure a client owned by local-advisor whose email is the traveler's (the link key).
# NOTE: this must happen BEFORE the traveler auth user exists — POST /clients issues
# an invite, and Supabase refuses to invite an email that is already a user (502).
# Wave F: GET /clients is a searchable {clients,…} envelope — ?q= matches email
# (and keeps the lookup honest now that the roster is paginated).
existing=$(curl -sS -G --data-urlencode "q=$TRV_EMAIL" "$API_URL/clients" -H "Authorization: Bearer $ADV_JWT" | python3 -c '
import json, sys
cs = json.load(sys.stdin)["clients"]
print(next((c["id"] for c in cs if c.get("email","").lower()==sys.argv[1].lower()), ""))' "$TRV_EMAIL")
if [[ -z "$existing" ]]; then
  body=$(python3 -c 'import json,sys; print(json.dumps({"full_name":"E2E Linked Traveler","email":sys.argv[1],"dossier":{"typed":{"contact_preference":"email","travel_party_notes":""}}}))' "$TRV_EMAIL")
  cid=$(curl -sS -X POST "$API_URL/clients" -H "Authorization: Bearer $ADV_JWT" -H 'content-type: application/json' -d "$body" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin).get("client_id",""))')
  [[ -n "$cid" ]] || die "failed to create the traveler-linked client"
  log "created traveler-linked client $cid (owner: local-advisor, email: $TRV_EMAIL)"
else
  log "traveler-linked client already exists ($existing)"
fi

# Now the client (and its invite) exist — safe to create the traveler auth user.
ensure_user "$TRV_EMAIL" "$TRV_ROLE" "$TRV_PW" >/dev/null

# Backfill the auth_user_id link by resolving /me/client as the traveler.
TRV_JWT=$(grant "$TRV_EMAIL" "$TRV_PW" "$TRV_ANON")
[[ -n "$TRV_JWT" ]] || die "traveler password grant failed (check local-traveler anon_key/password)"
linked=$(curl -sS "$API_URL/me/client" -H "Authorization: Bearer $TRV_JWT" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin).get("client_id",""))')
[[ -n "$linked" ]] || die "traveler GET /me/client did not resolve a client"
log "traveler links to client $linked"
log "done — local-advisor + local-traveler ready for the e2e suite."
