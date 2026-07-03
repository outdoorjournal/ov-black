#!/usr/bin/env bash
# scripts/cleanup-users.sh — delete users (auth + their client/itinerary/dossier
# graph) from the LOCAL or STAGING Supabase project. The bigger hammer next to
# cleanup-staging-e2e.sh (which only prunes the ephemeral e2e-*@ovblack.dev
# detritus on staging) and reset-client.sh (which resets one client but KEEPS the
# user). This one actually removes users.
#
# Default mode (bulk): delete EVERY auth user + their graph EXCEPT a keep-list of
# service identities (so the e2e suite + `ovb --profile *-advisor|*-traveler`
# keep working). Resolve the keep-list from the .cli profiles for the env, falling
# back to the documented defaults:
#   local   → local-advisor   / local-traveler    (ovb-advisor@example.com / ovb-traveler@example.com)
#   staging → staging-advisor / staging-traveler  (ovb-e2e-advisor@ovblack.dev / ovb-e2e-traveler@ovblack.dev)
# Extend the keep-list ad hoc with --keep a@b,c@d.
#
# Targeted mode (--email a@b[,c@d]): delete only those users + everything they
# own/are-linked-to (ignores the keep-list — explicit wins). Use it to drop your
# own login or a single demo account.
#
# Two stores, two channels (mirrors cleanup-staging-e2e.sh):
#   - clients + their graph: psql. itineraries.client_id is ON DELETE SET NULL
#     (not cascade), so itineraries are deleted explicitly by client_id FIRST
#     (that cascades nodes/edges/analyses); deleting the client then cascades
#     dossiers/facts/contacts/party/documents/sessions. clients.owner_id is ON
#     DELETE CASCADE, so deleting an advisor auth user would otherwise cascade its
#     owned clients and orphan their itineraries — we delete those clients first.
#   - auth users: Supabase admin API (DELETE /auth/v1/admin/users/{id}); that
#     cascades public.profiles.
#   - bulk mode also prunes already-orphaned itineraries (client_id IS NULL) left
#     by past deletes, unless --no-prune-orphans (the only way to a truly clean DB).
#
# Secrets (service-role key, DB DSN) are fetched into vars and NEVER echoed (R017).
#
# Usage:
#   scripts/cleanup-users.sh                              # LOCAL bulk, prompts
#   scripts/cleanup-users.sh --dry-run                   # LOCAL, count only
#   scripts/cleanup-users.sh --env staging --dry-run     # STAGING, count only
#   scripts/cleanup-users.sh --email me@x.com -y         # LOCAL, drop one user
#   scripts/cleanup-users.sh --keep me@x.com             # LOCAL bulk, also keep me@x.com
#   scripts/cleanup-users.sh --env staging -y            # STAGING bulk (careful!)
#
# Env overrides (local only): DB_URL, SUPABASE_URL.
set -euo pipefail

PREFIX="[cleanup-users]"
log() { printf '%s %s\n' "$PREFIX" "$*" >&2; }
die() { printf '%s ERROR: %s\n' "$PREFIX" "$*" >&2; exit 1; }

# ── args ─────────────────────────────────────────────────────────────────────
ENV=local
DRY_RUN=0
ASSUME_YES=0
EMAILS=""        # comma-sep targeted emails (targeted mode when set)
EXTRA_KEEP=""    # comma-sep extra keep-list emails (bulk mode)
PRUNE_ORPHANS=1  # bulk: also delete itineraries with client_id IS NULL

usage() { sed -n '2,55p' "$0"; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env) ENV="${2:?}"; shift 2;;
    --dry-run) DRY_RUN=1; shift;;
    --email) EMAILS="${EMAILS:+$EMAILS,}${2:?}"; shift 2;;
    --keep)  EXTRA_KEEP="${EXTRA_KEEP:+$EXTRA_KEEP,}${2:?}"; shift 2;;
    --no-prune-orphans) PRUNE_ORPHANS=0; shift;;
    -y|--yes) ASSUME_YES=1; shift;;
    -h|--help) usage; exit 0;;
    *) die "unknown flag: $1 (try --help)";;
  esac
done

[[ "$ENV" == local || "$ENV" == staging ]] || die "--env must be local or staging (got: $ENV)"
MODE="bulk"; [[ -n "$EMAILS" ]] && MODE="targeted"

for t in curl python3 psql; do command -v "$t" >/dev/null || die "$t not on PATH"; done

REPO_ROOT="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." && pwd )"
CLI="${OVB_CONFIG:-$HOME/.ovblack/.cli}"

validate_email_csv() {  # validate_email_csv <csv> <label>
  python3 - "$1" "$2" <<'PY' || exit 1
import re, sys
csv, label = sys.argv[1], sys.argv[2]
pat = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
for e in (x.strip() for x in csv.split(",") if x.strip()):
    if not pat.match(e):
        sys.stderr.write(f"invalid email in {label}: {e}\n"); sys.exit(1)
PY
}
[[ -n "$EMAILS" ]] && { validate_email_csv "$EMAILS" "--email" || die "bad --email value"; }
[[ -n "$EXTRA_KEEP" ]] && { validate_email_csv "$EXTRA_KEEP" "--keep" || die "bad --keep value"; }

# csv -> SQL quoted, lowercased, deduped list:  a@b,c@d -> 'a@b','c@d'  ('' -> "null")
csv_to_sqllist() {
  python3 - "${1:-}" <<'PY'
import sys
csv = sys.argv[1] if len(sys.argv) > 1 else ""
items = sorted({x.strip().lower() for x in csv.split(",") if x.strip()})
print(",".join("'" + i.replace("'", "''") + "'" for i in items) or "null")
PY
}

cli_get() {  # cli_get <profile> <key>  (empty when absent)
  [[ -f "$CLI" ]] || { printf ''; return; }
  python3 - "$CLI" "$1" "$2" <<'PY'
import configparser, sys
c = configparser.ConfigParser(interpolation=None)
try:
    c.read(sys.argv[1])
except Exception:
    print(""); raise SystemExit
print(c.get(f"profile {sys.argv[2]}", sys.argv[3], fallback=""))
PY
}

# ── coordinates + secrets per env ────────────────────────────────────────────
if [[ "$ENV" == local ]]; then
  SUPABASE_URL="${SUPABASE_URL:-http://127.0.0.1:54321}"
  DB_DSN="${DB_URL:-postgresql://postgres:postgres@127.0.0.1:54322/postgres}"
  SK="$(grep -E '^supabase_service_role_key=' "$REPO_ROOT/apps/api/.env" 2>/dev/null | cut -d= -f2- || true)"
  [[ -n "$SK" ]] || die "supabase_service_role_key missing from apps/api/.env"
  KEEP_DEFAULT="ovb-advisor@example.com,ovb-traveler@example.com"
  ADV_PROFILE="local-advisor"; TRV_PROFILE="local-traveler"
else
  command -v aws >/dev/null || die "aws not on PATH (needed for staging secrets)"
  export AWS_PROFILE="${AWS_PROFILE:-tov-sso}"
  export AWS_REGION="${AWS_REGION:-us-east-2}"
  SUPABASE_URL="$(python3 -c "import json;print(json.load(open('$REPO_ROOT/infra/cdk/cdk.json'))['context']['ov-black:envs']['staging']['supabaseUrl'])")"
  [[ -n "$SUPABASE_URL" ]] || die "could not read staging supabaseUrl from cdk.json"
  log "fetching staging secrets from Secrets Manager"
  SK="$(aws secretsmanager get-secret-value --secret-id ov-black/staging/supabase-service-role --query SecretString --output text 2>/dev/null)" \
    || die "service-role key unreadable (SSO expired? run: aws sso login --profile tov-sso)"
  DSN_RAW="$(aws secretsmanager get-secret-value --secret-id ov-black/staging/database-url --query SecretString --output text 2>/dev/null)" \
    || die "database-url unreadable"
  DB_DSN="${DSN_RAW/+asyncpg/}"
  KEEP_DEFAULT="ovb-e2e-advisor@ovblack.dev,ovb-e2e-traveler@ovblack.dev"
  ADV_PROFILE="staging-advisor"; TRV_PROFILE="staging-traveler"
fi

# ── keep-list (bulk only) — prefer .cli profiles, fall back to defaults ───────
KEEP_CSV=""
add_keep() { [[ -n "$1" ]] && KEEP_CSV="${KEEP_CSV:+$KEEP_CSV,}$1"; return 0; }
adv_email="$(cli_get "$ADV_PROFILE" email)"
trv_email="$(cli_get "$TRV_PROFILE" email)"
if [[ -n "$adv_email" || -n "$trv_email" ]]; then
  add_keep "$adv_email"; add_keep "$trv_email"
else
  KEEP_CSV="$KEEP_DEFAULT"
fi
add_keep "$EXTRA_KEEP"

# ── liveness ─────────────────────────────────────────────────────────────────
curl -sf -o /dev/null "$SUPABASE_URL/auth/v1/settings" -H "apikey: $SK" \
  || die "Supabase Auth unreachable at $SUPABASE_URL"
psql "$DB_DSN" -tAc "select 1" >/dev/null 2>&1 || die "DB unreachable (is the stack up?)"

# ── admin API helper ─────────────────────────────────────────────────────────
admin() {  # admin <METHOD> <PATH>
  curl -sS -X "$1" "$SUPABASE_URL$2" -H "apikey: $SK" -H "Authorization: Bearer $SK"
}

# ── 1. collect auth users to delete (paginated) → TMP_USERS (id<TAB>email) ────
# Program lives in a -c string (not a `python3 - <<PY` heredoc) so stdin stays the
# piped admin response rather than the heredoc'd program text.
read -r -d '' FILTER_PY <<'PY' || true
import json, sys
mode, keep_csv, target_csv = sys.argv[1], sys.argv[2], sys.argv[3]
keep   = {x.strip().lower() for x in keep_csv.split(",") if x.strip()}
target = {x.strip().lower() for x in target_csv.split(",") if x.strip()}
for u in (json.load(sys.stdin).get("users") or []):
    em = (u.get("email") or "").lower()
    if not em:
        continue
    hit = (em in target) if mode == "targeted" else (em not in keep)
    if hit:
        print(u["id"] + "\t" + em)
PY
TMP_USERS="$(mktemp)"
trap 'rm -f "$TMP_USERS"' EXIT
page=1
while :; do
  resp="$(admin GET "/auth/v1/admin/users?page=$page&per_page=1000")"
  n="$(printf '%s' "$resp" | python3 -c 'import json,sys; print(len(json.load(sys.stdin).get("users") or []))' 2>/dev/null || echo 0)"
  [[ "$n" -eq 0 ]] && break
  printf '%s' "$resp" | python3 -c "$FILTER_PY" "$MODE" "$KEEP_CSV" "$EMAILS" >>"$TMP_USERS"
  page=$((page+1)); [[ "$page" -gt 200 ]] && { log "WARN: stopped paging at 200 pages"; break; }
done
n_users="$(grep -c . "$TMP_USERS" || true)"

# ── 2. compute which clients to delete ───────────────────────────────────────
if [[ "$MODE" == targeted ]]; then
  TARGET_SQL="$(csv_to_sqllist "$EMAILS")"
  # clients whose traveler-email is targeted, OR owned by a targeted auth user
  # (so deleting an advisor cleanly removes their clients instead of orphaning).
  OWNER_SQL="$(cut -f1 "$TMP_USERS" | python3 -c 'import sys; ids=[l.strip() for l in sys.stdin if l.strip()]; print(",".join("\x27"+i+"\x27" for i in ids) or "null")')"
  CLIENT_WHERE="lower(email) in ($TARGET_SQL) or owner_id in ($OWNER_SQL)"
else
  KEEP_SQL="$(csv_to_sqllist "$KEEP_CSV")"
  CLIENT_WHERE="lower(email) not in ($KEEP_SQL)"
fi

n_clients="$(psql "$DB_DSN" -tAc "select count(*) from public.clients where $CLIENT_WHERE;")"
n_itin="$(psql "$DB_DSN" -tAc "select count(*) from public.itineraries where client_id in (select id from public.clients where $CLIENT_WHERE);")"
n_orphan=0
[[ "$MODE" == bulk && "$PRUNE_ORPHANS" == 1 ]] && \
  n_orphan="$(psql "$DB_DSN" -tAc "select count(*) from public.itineraries where client_id is null;")"

# ── plan summary ─────────────────────────────────────────────────────────────
log "env=$ENV mode=$MODE"
if [[ "$MODE" == bulk ]]; then
  log "keep-list: ${KEEP_CSV:-<none>}"
else
  log "targeting: $EMAILS"
fi
log "auth users to delete: $n_users"
log "clients to delete:    $n_clients (cascading their dossiers/facts/sessions; $n_itin itineraries deleted first)"
[[ "$n_orphan" -gt 0 ]] && log "orphan itineraries to prune (client_id IS NULL from past deletes): $n_orphan"
if [[ "$n_users" -gt 0 ]]; then
  log "sample of users to delete:"
  head -n 10 "$TMP_USERS" | cut -f2 | sed "s/^/$PREFIX     - /" >&2
  [[ "$n_users" -gt 10 ]] && log "    … and $((n_users-10)) more"
fi

if [[ "$n_users" -eq 0 && "$n_clients" -eq 0 && "$n_orphan" -eq 0 ]]; then
  log "nothing to do — already clean."
  exit 0
fi

if [[ "$DRY_RUN" == 1 ]]; then
  log "dry-run: nothing deleted."
  exit 0
fi

# ── confirm (louder for staging) ─────────────────────────────────────────────
if [[ "$ASSUME_YES" != 1 ]]; then
  if [[ "$ENV" == staging ]]; then
    printf '%s ⚠️  STAGING — type the word STAGING to proceed: ' "$PREFIX" >&2
    read -r ans; [[ "$ans" == "STAGING" ]] || { log "aborted"; exit 1; }
  else
    printf '%s proceed? [y/N] ' "$PREFIX" >&2
    read -r ans; [[ "$ans" =~ ^[Yy]$ ]] || { log "aborted"; exit 1; }
  fi
fi

# ── 3. delete clients + their graph (one transaction) ────────────────────────
if [[ "$n_clients" -gt 0 || "$n_orphan" -gt 0 ]]; then
  orphan_sql=""
  [[ "$n_orphan" -gt 0 ]] && orphan_sql="delete from public.itineraries where client_id is null;"
  psql "$DB_DSN" -v ON_ERROR_STOP=1 -q <<SQL
begin;
  delete from public.itineraries where client_id in (select id from public.clients where $CLIENT_WHERE);
  delete from public.clients where $CLIENT_WHERE;
  $orphan_sql
commit;
SQL
  log "deleted $n_clients clients + $n_itin itineraries${n_orphan:+ + $n_orphan orphan itineraries} (graph cascaded)"
fi

# ── 4. delete auth users (admin API; cascades profiles) ──────────────────────
if [[ "$n_users" -gt 0 ]]; then
  deleted=0
  while IFS=$'\t' read -r id em; do
    [[ -n "$id" ]] || continue
    # --retry rides out transient resets; || true keeps set -e from aborting the
    # loop on one blip (idempotent — re-run to mop up any misses).
    curl -sS --retry 3 --retry-connrefused -o /dev/null -X DELETE \
      "$SUPABASE_URL/auth/v1/admin/users/$id" -H "apikey: $SK" -H "Authorization: Bearer $SK" || true
    deleted=$((deleted+1))
  done <"$TMP_USERS"
  log "deleted $deleted auth users"
fi

log "done (env=$ENV)."
