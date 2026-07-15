#!/usr/bin/env bash
# scripts/cleanup-robin.sh — reset a demo traveler's self-expressed state.
#
# Targeted cleanup for re-running the Robin Thurston / Mt Olympus demo (or
# any client). Wipes exactly four things and nothing else:
#   - profile_facts       — what the traveler self-expressed (agent/advisor)
#   - itineraries         — cascades to nodes + edges (the whole graph)
#   - reading list        — the `article` nodes that live ON the itinerary,
#                           so they are removed by the itineraries cascade;
#                           counted separately below purely for reassurance.
#   - party_members       — the durable, client-scoped travel party (primary +
#                           companions). Client-scoped, so it is NOT touched by
#                           the itineraries cascade and needs its own delete;
#                           intake re-seats the party on the next demo run.
#
# What it does NOT touch (unlike reset-client.sh --reset-dossier):
#   - clients / auth.users     — the traveler can still log in
#   - dossiers + dossier_facts — private advisor knowledge
#   - osint_facts              — external research
#   - reading_catalog          — the shared Outside catalog is not per-client
#   - agent_sessions           — kept; their itinerary_id pin is set null by
#                                the FK's `on delete set null`, so no dangling
#
# Env overrides:
#   DB_URL              postgres dsn (default: local Supabase on :54322)
#   SUPABASE_CONTAINER  db container if no local psql is found
#                       (default: supabase_db_ov-black)

set -euo pipefail

PREFIX="[cleanup-robin]"
log() { printf '%s %s\n'        "$PREFIX" "$*"; }
die() { printf '%s ERROR: %s\n' "$PREFIX" "$*" >&2; exit 1; }

EMAIL="robin.thurston+demo@example.com"
ASSUME_YES=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --email) EMAIL="${2:?}"; shift 2;;
    -y|--yes) ASSUME_YES=1; shift;;
    -h|--help) sed -n '2,29p' "$0"; exit 0;;
    *) die "unknown flag: $1";;
  esac
done

[[ "$EMAIL" =~ ^[A-Za-z0-9._+-]+@[A-Za-z0-9.-]+$ ]] \
  || die "invalid email: $EMAIL"

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

# --- 1. resolve client_id by email
client_id=$(psql_exec -c "
  select id from public.clients
  where lower(email) = lower('${EMAIL//\'/\'\'}')
  limit 1;
" | tr -d '[:space:]')

[[ -n "$client_id" ]] || die "no clients row for email: $EMAIL"
log "client_id: $client_id ($EMAIL)"

# --- 2. show what will be deleted
counts=$(psql_exec -c "
  select
    (select count(*) from public.profile_facts where client_id = '$client_id'),
    (select count(*) from public.itineraries   where client_id = '$client_id'),
    (select count(*) from public.nodes n
       join public.itineraries i on i.id = n.itinerary_id
       where i.client_id = '$client_id'),
    (select count(*) from public.edges e
       join public.itineraries i on i.id = e.itinerary_id
       where i.client_id = '$client_id'),
    (select count(*) from public.nodes n
       join public.itineraries i on i.id = n.itinerary_id
       where i.client_id = '$client_id' and n.type = 'article'),
    (select count(*) from public.party_members where client_id = '$client_id');
")
IFS='|' read -r n_p_facts n_itins n_nodes n_edges n_articles n_party <<< "$counts"

log "to delete: ${n_p_facts} profile facts, ${n_itins} itineraries (${n_nodes} nodes / ${n_edges} edges), incl. ${n_articles} reading-list article(s), ${n_party} party member(s)"

if [[ "$n_p_facts" == "0" && "$n_itins" == "0" && "$n_party" == "0" ]]; then
  log "nothing to do — already clean"
  exit 0
fi

# --- 3. confirm
if [[ "$ASSUME_YES" != "1" ]]; then
  printf '%s proceed? [y/N] ' "$PREFIX"
  read -r ans
  [[ "$ans" =~ ^[Yy]$ ]] || { log "aborted"; exit 1; }
fi

# --- 4. delete in one transaction (article/reading-list nodes go with the
#        itineraries cascade — no separate delete needed)
psql_exec <<SQL
begin;
  delete from public.profile_facts where client_id = '$client_id';
  delete from public.itineraries   where client_id = '$client_id';
  delete from public.party_members where client_id = '$client_id';
commit;
SQL

log "done — profile facts, itineraries, reading list, and travel party cleared"
