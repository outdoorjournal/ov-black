#!/usr/bin/env bash
# scripts/seed-japan-demo.sh — instantiate the Japan demo template into a client.
#
# Resolves a client by email (or --client-id), mints an advisor JWT for the
# git user.email (the assumed calling advisor), and POSTs /demos/japan so a
# fresh draft itinerary lands on that client's account. Useful for showing
# off the system with a real-trip itinerary instead of the prototype fixture.
#
# Usage:
#   scripts/seed-japan-demo.sh --email ap@outdoorvoyage.com
#   scripts/seed-japan-demo.sh --client-id <uuid>
#   scripts/seed-japan-demo.sh --email ap@outdoorvoyage.com --use-original-dates
#   scripts/seed-japan-demo.sh --email ap@outdoorvoyage.com --title "AP — Japan Demo"
#
# Flags:
#   --email                client lookup by clients.email (case-insensitive)
#   --client-id            skip the lookup and use this UUID directly
#   --api-url              override the API base (default: http://localhost:8000)
#   --advisor-email        whose JWT to mint (default: git user.email)
#   --title                optional title for the itinerary (default: template name)
#   --trip-start           ISO-8601 datetime for the new trip start (default: today + 30d UTC)
#   --use-original-dates   shorthand for --trip-start 2024-06-20T00:00:00+09:00
#   -y, --yes              skip the confirmation prompt
#
# Env overrides:
#   DB_URL              postgres dsn (default: local Supabase on :54322)
#   SUPABASE_CONTAINER  db container if no local psql is found
#                       (default: supabase_db_ov-black)

set -euo pipefail

PREFIX="[seed-japan]"
log() { printf '%s %s\n'        "$PREFIX" "$*" >&2; }
die() { printf '%s ERROR: %s\n' "$PREFIX" "$*" >&2; exit 1; }

REPO_ROOT="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." && pwd )"

EMAIL=""
CLIENT_ID=""
API_URL="${OV_BLACK_API_URL:-http://localhost:8000}"
ADVISOR_EMAIL=""
TITLE=""
TRIP_START=""
ASSUME_YES=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --email)              EMAIL="${2:?}"; shift 2;;
    --client-id)          CLIENT_ID="${2:?}"; shift 2;;
    --api-url)            API_URL="${2:?}"; shift 2;;
    --advisor-email)      ADVISOR_EMAIL="${2:?}"; shift 2;;
    --title)              TITLE="${2:?}"; shift 2;;
    --trip-start)         TRIP_START="${2:?}"; shift 2;;
    --use-original-dates) TRIP_START="2024-06-20T00:00:00+09:00"; shift;;
    -y|--yes)             ASSUME_YES=1; shift;;
    -h|--help)            sed -n '2,33p' "$0"; exit 0;;
    *) die "unknown flag: $1";;
  esac
done

[[ -n "$EMAIL" || -n "$CLIENT_ID" ]] \
  || die "one of --email or --client-id is required"

DB_URL="${DB_URL:-postgresql://postgres:postgres@127.0.0.1:54322/postgres}"
SUPABASE_CONTAINER="${SUPABASE_CONTAINER:-supabase_db_ov-black}"

# psql: prefer host, fall back to docker exec into the supabase_db container.
if command -v psql >/dev/null 2>&1; then
  psql_exec() { psql "$DB_URL" -v ON_ERROR_STOP=1 -q -t -A "$@"; }
else
  command -v docker >/dev/null 2>&1 \
    || die "no local psql and docker not installed — install one"
  docker exec "$SUPABASE_CONTAINER" true >/dev/null 2>&1 \
    || die "supabase db container '$SUPABASE_CONTAINER' is not running (is \`supabase start\` up?)"
  psql_exec() { docker exec -i "$SUPABASE_CONTAINER" \
    psql -U postgres -d postgres -v ON_ERROR_STOP=1 -q -t -A "$@"; }
fi

# --- 1. resolve client_id (and the client's owner so we can sanity-check
#         the calling advisor before bothering the API).
if [[ -z "$CLIENT_ID" ]]; then
  log "looking up client by email: $EMAIL"
  row=$(psql_exec -c "
    select c.id, lower(c.email), coalesce(u.email, '')
      from public.clients c
      left join auth.users u on u.id = c.owner_id
     where lower(c.email) = lower('${EMAIL//\'/\'\'}')
     limit 1;
  ")
  [[ -n "$row" ]] || die "no clients row for email: $EMAIL"
  IFS='|' read -r CLIENT_ID _client_email OWNER_EMAIL <<< "$row"
  log "client_id:    $CLIENT_ID"
  log "owner email:  ${OWNER_EMAIL:-<none>}"
fi

# --- 2. resolve the calling advisor email
if [[ -z "$ADVISOR_EMAIL" ]]; then
  ADVISOR_EMAIL="$(git -C "$REPO_ROOT" config user.email 2>/dev/null || true)"
  [[ -n "$ADVISOR_EMAIL" ]] \
    || die "couldn't read git user.email; pass --advisor-email <addr>"
fi
log "advisor:      $ADVISOR_EMAIL"
log "api:          $API_URL"

# Friendly heads-up if the advisor doesn't own the client. The API will
# 403 anyway, but failing here gives a clearer message.
if [[ -n "${OWNER_EMAIL:-}" ]] \
   && [[ "$(echo "$OWNER_EMAIL" | tr '[:upper:]' '[:lower:]')" != \
         "$(echo "$ADVISOR_EMAIL" | tr '[:upper:]' '[:lower:]')" ]]; then
  log "WARNING: client is owned by '$OWNER_EMAIL', not '$ADVISOR_EMAIL'"
  log "         the API will 403 unless you pass --advisor-email correctly"
fi

# --- 3. confirm
if [[ "$ASSUME_YES" != "1" ]]; then
  if [[ -n "$TRIP_START" ]]; then
    log "trip starts:  $TRIP_START"
  else
    log "trip starts:  today + 30 days (server default)"
  fi
  printf '%s proceed? [y/N] ' "$PREFIX" >&2
  read -r ans
  [[ "$ans" =~ ^[Yy]$ ]] || { log "aborted"; exit 1; }
fi

# --- 4. mint advisor JWT
log "minting advisor JWT for $ADVISOR_EMAIL"
JWT="$(SUPABASE_URL="${SUPABASE_URL:-}" \
       SUPABASE_SERVICE_ROLE_KEY="${SUPABASE_SERVICE_ROLE_KEY:-}" \
       "$REPO_ROOT/scripts/mint-jwt.sh" --email "$ADVISOR_EMAIL")"
[[ -n "$JWT" ]] || die "mint-jwt.sh returned empty"

# --- 5. POST /demos/japan
body="{\"client_id\":\"$CLIENT_ID\""
if [[ -n "$TITLE"      ]]; then body="$body,\"title\":\"${TITLE//\"/\\\"}\""; fi
if [[ -n "$TRIP_START" ]]; then body="$body,\"trip_start_at\":\"$TRIP_START\""; fi
body="$body}"

log "POST $API_URL/demos/japan"
http_status=$(curl -sS -o /tmp/seed-japan-resp.json -w "%{http_code}" \
  -X POST "$API_URL/demos/japan" \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d "$body")

if [[ "$http_status" != "201" ]]; then
  log "API returned $http_status:"
  cat /tmp/seed-japan-resp.json >&2
  printf '\n' >&2
  exit 1
fi

# Pretty-print the response to stderr.
python3 -m json.tool /tmp/seed-japan-resp.json >&2

# Surface the itinerary id on stdout (the only line on stdout — composes
# with `xargs` etc.).
itinerary_id="$(python3 -c \
  "import json; print(json.load(open('/tmp/seed-japan-resp.json'))['itinerary_id'])" \
)"
printf '%s\n' "$itinerary_id"

log "done. open: ${OV_BLACK_WEB_URL:-http://localhost:3000}/command-center/itineraries/$itinerary_id"
