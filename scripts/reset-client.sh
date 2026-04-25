#!/usr/bin/env bash
# scripts/reset-client.sh — wipe a client's conversation + itinerary state.
#
# Resets a client back to the basecamp first-touch experience:
#   - deletes agent_sessions (cascades to agent_turns)
#   - deletes itineraries (cascades to nodes + edges)
# After running, /basecamp will render the `first_prompt` variant for
# that client on next load (turn_count == 0 AND no itineraries).
#
# What it does NOT touch:
#   - clients row, auth.users row — the user can log back in
#   - dossiers typed core — advisor-authored client basics
#   - dossier_facts / profile_facts / osint_facts — per-fact rows
# Pass --reset-dossier to also clear the typed core back to defaults
# AND truncate dossier_facts + profile_facts + osint_facts for the client.
#
# Env overrides:
#   DB_URL              postgres dsn (default: local Supabase on :54322)
#   SUPABASE_CONTAINER  db container if no local psql is found
#                       (default: supabase_db_ov-black)

set -euo pipefail

PREFIX="[reset-client]"
log() { printf '%s %s\n'        "$PREFIX" "$*"; }
die() { printf '%s ERROR: %s\n' "$PREFIX" "$*" >&2; exit 1; }

EMAIL=""
RESET_DOSSIER=0
ASSUME_YES=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --email) EMAIL="${2:?}"; shift 2;;
    --reset-dossier) RESET_DOSSIER=1; shift;;
    -y|--yes) ASSUME_YES=1; shift;;
    -h|--help) sed -n '2,24p' "$0"; exit 0;;
    *) die "unknown flag: $1";;
  esac
done

[[ -n "$EMAIL" ]] || die "--email is required"
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
log "client_id: $client_id"

# --- 2. show what will be deleted
counts=$(psql_exec -c "
  select
    (select count(*) from public.agent_sessions where client_id = '$client_id'),
    (select count(*) from public.agent_turns t
       join public.agent_sessions s on s.id = t.session_id
       where s.client_id = '$client_id'),
    (select count(*) from public.itineraries where client_id = '$client_id'),
    (select count(*) from public.nodes n
       join public.itineraries i on i.id = n.itinerary_id
       where i.client_id = '$client_id'),
    (select count(*) from public.edges e
       join public.itineraries i on i.id = e.itinerary_id
       where i.client_id = '$client_id'),
    (select count(*) from public.dossiers where client_id = '$client_id'),
    (select count(*) from public.dossier_facts where client_id = '$client_id'),
    (select count(*) from public.profile_facts where client_id = '$client_id'),
    (select count(*) from public.osint_facts   where client_id = '$client_id');
")
IFS='|' read -r n_sessions n_turns n_itins n_nodes n_edges n_dossiers n_d_facts n_p_facts n_o_facts <<< "$counts"

log "to delete: ${n_sessions} sessions, ${n_turns} turns, ${n_itins} itineraries, ${n_nodes} nodes, ${n_edges} edges"
if [[ "$RESET_DOSSIER" == "1" ]]; then
  log "+ reset dossier typed core (${n_dossiers} row(s)) and truncate ${n_d_facts}/${n_p_facts}/${n_o_facts} dossier/profile/osint facts"
fi

if [[ "$n_sessions" == "0" && "$n_turns" == "0" && "$n_itins" == "0" && "$RESET_DOSSIER" != "1" ]]; then
  log "nothing to do — client is already fresh"
  exit 0
fi

# --- 3. confirm
if [[ "$ASSUME_YES" != "1" ]]; then
  printf '%s proceed? [y/N] ' "$PREFIX"
  read -r ans
  [[ "$ans" =~ ^[Yy]$ ]] || { log "aborted"; exit 1; }
fi

# --- 4. delete in one transaction
sql_reset_dossier=""
if [[ "$RESET_DOSSIER" == "1" ]]; then
  sql_reset_dossier="
    update public.dossiers set
      travel_party_notes      = '',
      estimated_net_worth_usd = null,
      updated_at              = now()
    where client_id = '$client_id';
    delete from public.dossier_facts where client_id = '$client_id';
    delete from public.profile_facts where client_id = '$client_id';
    delete from public.osint_facts   where client_id = '$client_id';
  "
fi

psql_exec <<SQL
begin;
  delete from public.agent_sessions where client_id = '$client_id';
  delete from public.itineraries    where client_id = '$client_id';
  $sql_reset_dossier
commit;
SQL

log "done — client is fresh"
