#!/usr/bin/env bash
# Provision the "Robin Thurston / Mt Olympus" campaign demo subject.
#
# The campaign itinerary itself is created LIVE when the traveler clicks the CTA
# (POST /demos/campaign/olympus is traveler-self-serve, so intake runs on their
# fork). This script does the one thing that must happen ahead of time: it
# find-or-creates the Robin client and hand-seeds his three fact tiers
# (flattering + non-creepy), then prints the campaign landing URL to open while
# logged in as Robin.
#
# Usage:
#   scripts/seed-campaign.sh                      # reuse/create the Robin client
#   scripts/seed-campaign.sh --client-id <uuid>   # seed facts onto an existing client
#   scripts/seed-campaign.sh --email robin@x.com  # create + seed with this email
#
# Env overrides:
#   API_URL   (default http://localhost:8000)
#   WEB_URL   (default http://localhost:3000)
#   CAMPAIGN  (default olympus)
#   ADVISOR_EMAIL  (default: git user.email, via mint-jwt.sh)
set -euo pipefail

API_URL="${API_URL:-http://localhost:8000}"
WEB_URL="${WEB_URL:-http://localhost:3000}"
CAMPAIGN="${CAMPAIGN:-olympus}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

CLIENT_ID=""
CLIENT_EMAIL=""
CLIENT_NAME="Robin Thurston"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --client-id) CLIENT_ID="$2"; shift 2;;
    --email) CLIENT_EMAIL="$2"; shift 2;;
    --name) CLIENT_NAME="$2"; shift 2;;
    -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0;;
    *) echo "unknown arg: $1" >&2; exit 2;;
  esac
done

say() { printf '\033[1;36m• %s\033[0m\n' "$*" >&2; }
die() { printf '\033[1;31m✗ %s\033[0m\n' "$*" >&2; exit 1; }
jget() { python3 -c 'import sys,json; d=json.loads(sys.argv[1]); print(eval(sys.argv[2]))' "$1" "$2"; }

say "Minting advisor JWT…"
if [[ -n "${ADVISOR_EMAIL:-}" ]]; then
  JWT="$("$SCRIPT_DIR/mint-jwt.sh" --email "$ADVISOR_EMAIL" --role advisor)"
else
  JWT="$("$SCRIPT_DIR/mint-jwt.sh")"
fi
[[ -n "$JWT" ]] || die "could not mint a JWT (is local Supabase up?)"
auth=(-H "Authorization: Bearer $JWT")

# ── Resolve / create the Robin client ─────────────────────────────────
if [[ -z "$CLIENT_ID" ]]; then
  [[ -n "$CLIENT_EMAIL" ]] || CLIENT_EMAIL="robin.thurston+demo@example.com"
  say "Looking for an existing client with email <$CLIENT_EMAIL>…"
  clients=$(curl -fsS "${auth[@]}" "$API_URL/clients")
  CLIENT_ID=$(python3 -c '
import sys,json
d=json.loads(sys.argv[1]); email=sys.argv[2]
for c in d.get("clients",[]):
    if (c.get("email") or "").lower()==email.lower(): print(c["id"]); break
' "$clients" "$CLIENT_EMAIL")
  if [[ -z "$CLIENT_ID" ]]; then
    say "Creating client '$CLIENT_NAME' <$CLIENT_EMAIL>…"
    body=$(python3 -c 'import json,sys; print(json.dumps({
      "full_name": sys.argv[1], "email": sys.argv[2],
      "dossier": {"typed": {
        "contact_preference": "email",
        "travel_party_notes": "Wife and three children; based in Boulder, Colorado."
      }}
    }))' "$CLIENT_NAME" "$CLIENT_EMAIL")
    resp=$(curl -fsS "${auth[@]}" -H 'Content-Type: application/json' -X POST "$API_URL/clients" -d "$body") \
      || die "client create failed"
    CLIENT_ID=$(jget "$resp" 'd["client_id"]')
  fi
fi
say "Target client: $CLIENT_ID"

# ── Hand-seed the three fact tiers ────────────────────────────────────
# profile = referenceable (the agent may mention these naturally);
# dossier = private grounding (never revealed verbatim);
# osint   = external research (NEVER surfaced). All flattering, none creepy.
post_fact() {  # <tier> <kind> <text>
  local tier="$1" kind="$2" text="$3"
  body=$(python3 -c 'import json,sys; print(json.dumps({"kind":sys.argv[1],"text":sys.argv[2],"source_kind":"advisor"}))' "$kind" "$text")
  curl -fsS "${auth[@]}" -H 'Content-Type: application/json' \
    -X POST "$API_URL/clients/$CLIENT_ID/$tier/facts" -d "$body" >/dev/null \
    && printf '  ✓ %-8s %s\n' "$tier" "$kind" >&2 \
    || printf '  – %-8s %s (skipped/exists)\n' "$tier" "$kind" >&2
}

say "Seeding profile facts (referenceable)…"
post_fact profile passion         "Lifelong cyclist — started riding and racing in the early 1980s."
post_fact profile travel_history  "Colorado at heart; happiest on a mountain or a long ride."
post_fact profile preference      "Prefers active, outdoors-first travel over polished resort luxury."
post_fact profile aspiration      "Drawn to iconic, story-rich mountains."

say "Seeding dossier facts (private grounding)…"
post_fact dossier motivation      "Founder & CEO of Outside Inc.; built MapMyFitness and led Connected Fitness at Under Armour."
post_fact dossier preference      "Values authenticity and being genuinely understood; dislikes generic, impersonal service."
post_fact dossier party           "Travels as a family — wife and three children."

say "Seeding OSINT facts (never surfaced)…"
post_fact osint press             "Widely covered as a serial entrepreneur across fitness + media."
post_fact osint company           "Outside Inc. spans 38 active-lifestyle brands (Outside, Climbing, Backpacker, …)."
post_fact osint public_record     "MS in Finance, University of Colorado Denver; lives in Boulder."

printf '\n\033[1;32m✓ Robin provisioned for the %s campaign\033[0m\n' "$CAMPAIGN" >&2
printf '  client_id : %s\n' "$CLIENT_ID" >&2
printf '  Next: log in as Robin (the traveler), then open the campaign CTA:\n' >&2
printf '  landing   : \033[4m%s/campaign/%s\033[0m\n' "$WEB_URL" "$CAMPAIGN" >&2

# Stdout = just the client id, so the script composes into other tooling.
echo "$CLIENT_ID"
