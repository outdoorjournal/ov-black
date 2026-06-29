#!/usr/bin/env bash
# Inject a Japan demo itinerary into a traveler's account so the running app
# has a real, visualizable starter graph (instead of an empty one).
#
# By default it builds from LIVE inventory — Duffel flights + Google Places
# meals/experiences — via POST /demos/japan-live (results are cached server-side
# so repeat runs are fast). Pass --static to instead instantiate the
# hand-authored template (POST /demos/japan), which covers every card type but
# is canned. Either way it mints an advisor JWT, find-or-creates the client,
# seeds, and prints the deep link.
#
# Usage:
#   scripts/seed-japan.sh                         # LIVE build; reuse first client, else create one
#   scripts/seed-japan.sh --static                # static hand-authored template instead
#   scripts/seed-japan.sh --client-id <uuid>      # seed an existing client
#   scripts/seed-japan.sh --email a@b.com --name "Mr. & Mrs. Ito"   # create + seed
#   scripts/seed-japan.sh --trip-start 2026-07-10 # anchor the trip start date
#
# Env overrides:
#   API_URL   (default http://localhost:8000)
#   WEB_URL   (default http://localhost:3000)
#   ADVISOR_EMAIL  (default: git user.email, via mint-jwt.sh)
set -euo pipefail

API_URL="${API_URL:-http://localhost:8000}"
WEB_URL="${WEB_URL:-http://localhost:3000}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

CLIENT_ID=""
CLIENT_EMAIL=""
CLIENT_NAME="Mr. & Mrs. Demo (Japan starter)"
TRIP_START=""
TITLE=""
STATIC=0   # default: build from LIVE inventory (Duffel + Google Places)

while [[ $# -gt 0 ]]; do
  case "$1" in
    --client-id) CLIENT_ID="$2"; shift 2;;
    --email) CLIENT_EMAIL="$2"; shift 2;;
    --name) CLIENT_NAME="$2"; shift 2;;
    --trip-start) TRIP_START="$2"; shift 2;;
    --title) TITLE="$2"; shift 2;;
    --static) STATIC=1; shift;;
    -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0;;
    *) echo "unknown arg: $1" >&2; exit 2;;
  esac
done

say() { printf '\033[1;36m• %s\033[0m\n' "$*" >&2; }
die() { printf '\033[1;31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

# jget <json> <python-expression-on-`d`>  — parse JSON from stdin-less arg.
jget() { python3 -c 'import sys,json; d=json.loads(sys.argv[1]); print(eval(sys.argv[2]))' "$1" "$2"; }

say "Minting advisor JWT…"
if [[ -n "${ADVISOR_EMAIL:-}" ]]; then
  JWT="$("$SCRIPT_DIR/mint-jwt.sh" --email "$ADVISOR_EMAIL" --role advisor)"
else
  JWT="$("$SCRIPT_DIR/mint-jwt.sh")"
fi
[[ -n "$JWT" ]] || die "could not mint a JWT (is local Supabase up?)"

auth=(-H "Authorization: Bearer $JWT")

# ── Resolve the target client ─────────────────────────────────────────
if [[ -z "$CLIENT_ID" ]]; then
  if [[ -n "$CLIENT_EMAIL" ]]; then
    say "Creating client '$CLIENT_NAME' <$CLIENT_EMAIL>…"
    body=$(python3 -c 'import json,sys; print(json.dumps({"full_name":sys.argv[1],"email":sys.argv[2],"dossier":{"typed":{"contact_preference":"email","travel_party_notes":"Seeded Japan starter."}}}))' "$CLIENT_NAME" "$CLIENT_EMAIL")
    resp=$(curl -fsS "${auth[@]}" -H 'Content-Type: application/json' -X POST "$API_URL/clients" -d "$body") \
      || die "client create failed"
    CLIENT_ID=$(jget "$resp" 'd["client_id"]')
  else
    say "No --client-id given; checking for an existing client…"
    clients=$(curl -fsS "${auth[@]}" "$API_URL/clients")
    count=$(jget "$clients" 'len(d)')
    if [[ "$count" -gt 0 ]]; then
      CLIENT_ID=$(jget "$clients" 'd[0]["id"]')
      name=$(jget "$clients" 'd[0]["full_name"]')
      say "Reusing existing client: $name ($CLIENT_ID)"
    else
      CLIENT_EMAIL="japan-demo+$(date +%s)@example.com"
      say "No clients yet; creating '$CLIENT_NAME' <$CLIENT_EMAIL>…"
      body=$(python3 -c 'import json,sys; print(json.dumps({"full_name":sys.argv[1],"email":sys.argv[2],"dossier":{"typed":{"contact_preference":"email","travel_party_notes":"Seeded Japan starter."}}}))' "$CLIENT_NAME" "$CLIENT_EMAIL")
      resp=$(curl -fsS "${auth[@]}" -H 'Content-Type: application/json' -X POST "$API_URL/clients" -d "$body") \
        || die "client create failed"
      CLIENT_ID=$(jget "$resp" 'd["client_id"]')
    fi
  fi
fi
say "Target client: $CLIENT_ID"

# ── Build the /demos/japan payload ────────────────────────────────────
payload_py='import json,sys
out={"client_id":sys.argv[1]}
if sys.argv[2]: out["trip_start_at"]=sys.argv[2]+"T00:00:00Z"
if sys.argv[3]: out["title"]=sys.argv[3]
print(json.dumps(out))'
payload=$(python3 -c "$payload_py" "$CLIENT_ID" "$TRIP_START" "$TITLE")

if [[ "$STATIC" -eq 1 ]]; then
  ENDPOINT="$API_URL/demos/japan"
  say "Instantiating the static Japan template…"
else
  ENDPOINT="$API_URL/demos/japan-live"
  say "Building the Japan itinerary from LIVE inventory (Duffel + Google Places) — first run hits the providers, then it's cached…"
fi

resp=$(curl -fsS --max-time 180 "${auth[@]}" -H 'Content-Type: application/json' -X POST "$ENDPOINT" -d "$payload") \
  || die "POST ${ENDPOINT##*/} failed"

ITIN=$(jget "$resp" 'd["itinerary_id"]')
NODES=$(jget "$resp" 'd["node_count"]')
EDGES=$(jget "$resp" 'd["edge_count"]')

printf '\n\033[1;32m✓ Japan itinerary seeded\033[0m\n' >&2
printf '  itinerary_id : %s\n' "$ITIN" >&2
printf '  client_id    : %s\n' "$CLIENT_ID" >&2
printf '  nodes/edges  : %s / %s\n' "$NODES" "$EDGES" >&2
if [[ "$STATIC" -eq 0 ]]; then
  # Show what the providers actually returned vs. skipped — never a silent gap.
  python3 -c 'import sys,json; d=json.loads(sys.argv[1]); [print("  ✓ "+s) for s in d.get("sourced",[])]; [print("  – skipped: "+s) for s in d.get("skipped",[])]' "$resp" >&2
fi
printf '  visualize    : \033[4m%s/itinerary/%s\033[0m\n' "$WEB_URL" "$ITIN" >&2

# Stdout = just the itinerary id, so the script composes into other tooling.
echo "$ITIN"
