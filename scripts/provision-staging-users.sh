#!/usr/bin/env bash
# scripts/provision-staging-users.sh — staging analogue of provision-local-users.sh.
#
# Stands up the two password-grant service users the e2e suite + `ovb --profile
# staging-advisor|staging-traveler` rely on, against the REAL staging Supabase
# project + staging API. The one privileged DB write it needs (the advisor's
# public.profiles role) goes through psql against the session pooler — the same
# channel the local script uses, and NOT the Supabase Data API / PostgREST, which
# is intentionally disabled on this project (apps/api is the only DB surface).
#
# What it does (idempotent):
#   1. Reads the service-role key from Secrets Manager (ov-black/staging/...),
#      and the non-secret Supabase URL / anon key / API host from cdk.json.
#   2. Ensures a confirmed `staging-advisor` auth user (admin API) with a password,
#      and upserts its public.profiles row with role=advisor (PostgREST, service-role).
#   3. As that advisor, ensures a `clients` row whose email is the traveler's
#      (POST /clients — which issues the invite that CREATES the traveler auth user).
#   4. Sets the traveler's password (admin API) and resolves GET /me/client as the
#      traveler, which backfills clients.auth_user_id + upserts role=client.
#   5. Writes/refreshes the [profile staging|staging-advisor|staging-traveler]
#      sections in ~/.ovblack/.cli (passwords stay in-process; never printed).
#
# Secrets discipline (R017): the service-role key and the generated passwords are
# never echoed to stdout/stderr; only non-secret progress lines are logged.
#
# Prereqs: AWS SSO session for tov-sso (`aws sso login --profile tov-sso`),
#          curl + python3 + openssl on PATH.
#
# Usage:  scripts/provision-staging-users.sh
set -euo pipefail

PREFIX="[provision-staging-users]"
log() { printf '%s %s\n' "$PREFIX" "$*" >&2; }
die() { printf '%s ERROR: %s\n' "$PREFIX" "$*" >&2; exit 1; }

REPO_ROOT="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." && pwd )"
export AWS_PROFILE="${AWS_PROFILE:-tov-sso}"
export AWS_REGION="${AWS_REGION:-us-east-2}"

command -v aws    >/dev/null || die "aws not on PATH"
command -v curl   >/dev/null || die "curl not on PATH"
command -v python3>/dev/null || die "python3 not on PATH"
command -v openssl>/dev/null || die "openssl not on PATH"
command -v psql   >/dev/null || die "psql not on PATH"

CLI="${OVB_CONFIG:-$HOME/.ovblack/.cli}"
[[ -f "$CLI" ]] || die ".cli not found at $CLI (set OVB_CONFIG)"

# ── Non-secret staging coordinates (from infra/cdk/cdk.json staging context) ──
read_cdk() {  # read_cdk <key>
  python3 - "$REPO_ROOT/infra/cdk/cdk.json" "$1" <<'PY'
import json, sys
with open(sys.argv[1]) as fh:
    cfg = json.load(fh)
print(cfg["context"]["ov-black:envs"]["staging"][sys.argv[2]])
PY
}
SUPABASE_URL="$(read_cdk supabaseUrl)"
ANON_KEY="$(read_cdk supabaseAnonKey)"
API_HOST="$(read_cdk apiHost)"
API_URL="https://${API_HOST}"
[[ -n "$SUPABASE_URL" && -n "$ANON_KEY" && -n "$API_HOST" ]] || die "cdk.json staging context incomplete"
log "staging: api=$API_URL supabase=$SUPABASE_URL"

# ── Secrets — fetched into vars, never echoed ────────────────────────────────
log "fetching service-role key + database DSN from Secrets Manager"
SK="$(aws secretsmanager get-secret-value \
        --secret-id ov-black/staging/supabase-service-role \
        --query SecretString --output text 2>/dev/null)" \
  || die "could not read ov-black/staging/supabase-service-role (SSO session expired? run: aws sso login --profile tov-sso)"
[[ -n "$SK" && "$SK" != "REPLACE_ME" ]] || die "service-role secret is empty/placeholder"

# DB DSN for the single privileged write (advisor role). Rewrite the app's async
# scheme (postgresql+asyncpg://) to the plain one psql understands.
DB_DSN_RAW="$(aws secretsmanager get-secret-value \
        --secret-id ov-black/staging/database-url \
        --query SecretString --output text 2>/dev/null)" \
  || die "could not read ov-black/staging/database-url"
DB_DSN="${DB_DSN_RAW/+asyncpg/}"
[[ "$DB_DSN" == postgresql://* ]] || die "database-url secret is empty/placeholder"

# Liveness probes (non-secret).
curl -sf -o /dev/null "$SUPABASE_URL/auth/v1/settings" -H "apikey: $ANON_KEY" \
  || die "Supabase Auth unreachable at $SUPABASE_URL"
curl -sf -o /dev/null "$API_URL/health" || die "staging API unreachable at $API_URL/health"

# ── Identities ───────────────────────────────────────────────────────────────
# Plus-address one deliverable mailbox: the traveler-linked client is created via
# POST /clients, whose Supabase invite emails a welcome link through Resend — an
# undeliverable domain (.dev/example.com) fails the send with 500 (→ 502). Stable
# +tags keep the two service identities constant across runs. Override the base
# via $OVB_E2E_EMAIL_BASE (shared with the e2e suites).
EMAIL_BASE="${OVB_E2E_EMAIL_BASE:-chris@outdoorvoyage.com}"
EMAIL_LOCAL="${EMAIL_BASE%@*}"; EMAIL_DOMAIN="${EMAIL_BASE#*@}"
ADV_EMAIL="${EMAIL_LOCAL}+ovb-e2e-advisor@${EMAIL_DOMAIN}"
TRV_EMAIL="${EMAIL_LOCAL}+ovb-e2e-traveler@${EMAIL_DOMAIN}"

cli_get() {  # cli_get <profile> <key>  (empty string when absent)
  python3 - "$CLI" "$1" "$2" <<'PY'
import configparser, sys
c = configparser.ConfigParser(interpolation=None)
c.read(sys.argv[1])
print(c.get(f"profile {sys.argv[2]}", sys.argv[3], fallback=""))
PY
}
# Reuse existing passwords on re-run (so live sessions/passwords don't churn).
gen_pw() { openssl rand -base64 18 | tr -d '/+=' | cut -c1-20; }
ADV_PW="$(cli_get staging-advisor password)";  [[ -n "$ADV_PW" ]]  || ADV_PW="$(gen_pw)"
TRV_PW="$(cli_get staging-traveler password)";  [[ -n "$TRV_PW" ]]  || TRV_PW="$(gen_pw)"

# ── Supabase admin / PostgREST helpers (service-role) ────────────────────────
admin() {  # admin <METHOD> <PATH> [JSON_BODY]
  local m="$1" p="$2" b="${3:-}"
  if [[ -n "$b" ]]; then
    curl -sS -X "$m" "$SUPABASE_URL$p" -H "apikey: $SK" -H "Authorization: Bearer $SK" \
      -H 'content-type: application/json' -d "$b"
  else
    curl -sS -X "$m" "$SUPABASE_URL$p" -H "apikey: $SK" -H "Authorization: Bearer $SK"
  fi
}

upsert_profile_role() {  # upsert_profile_role <uid> <advisor|client>
  # Direct DB write via the session pooler (Data API stays disabled). The uid is a
  # Supabase-issued UUID, so it is safe to interpolate; no secret is on the cmdline.
  psql "$DB_DSN" -v ON_ERROR_STOP=1 -q -c \
    "insert into public.profiles (id, role) values ('$1', '$2')
     on conflict (id) do update set role = excluded.role;" \
    || die "profiles upsert for ${1:0:8}… role=$2 failed (psql)"
}

grant() {  # grant <email> <password> -> prints access_token (empty on failure)
  curl -sS -X POST "$SUPABASE_URL/auth/v1/token?grant_type=password" \
    -H "apikey: $ANON_KEY" -H 'content-type: application/json' \
    -d "$(python3 -c 'import json,sys; print(json.dumps({"email":sys.argv[1],"password":sys.argv[2]}))' "$1" "$2")" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin).get("access_token",""))'
}

ensure_user() {  # ensure_user <email> <password> -> prints uid (creates or updates password+confirm)
  local email="$1" pw="$2" users uid body email_q
  # URL-encode the email for the ?filter= query — a plus-addressed mailbox
  # (chris+tag@…) would otherwise have its '+' read as a space, missing the
  # existing user and forcing a duplicate create.
  email_q=$(python3 -c 'import sys,urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$email")
  users=$(admin GET "/auth/v1/admin/users?filter=$email_q")
  uid=$(printf '%s' "$users" | python3 -c '
import json, sys
us = json.load(sys.stdin).get("users") or []
print(next((u["id"] for u in us if u.get("email","").lower()==sys.argv[1].lower()), ""))' "$email")
  body=$(python3 -c 'import json,sys; print(json.dumps({"email":sys.argv[1],"password":sys.argv[2],"email_confirm":True}))' "$email" "$pw")
  if [[ -z "$uid" ]]; then
    uid=$(admin POST "/auth/v1/admin/users" "$body" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("id",""))')
    [[ -n "$uid" ]] || die "failed to create auth user $email"
    log "created auth user $email"
  else
    admin PUT "/auth/v1/admin/users/$uid" "$body" >/dev/null
    log "updated password/confirm for existing auth user $email"
  fi
  printf '%s' "$uid"
}

# ── 1–2. advisor user + role=advisor ─────────────────────────────────────────
ADV_UID=$(ensure_user "$ADV_EMAIL" "$ADV_PW")
upsert_profile_role "$ADV_UID" advisor
log "advisor profile role set (uid ${ADV_UID:0:8}…)"

ADV_JWT=$(grant "$ADV_EMAIL" "$ADV_PW")
[[ -n "$ADV_JWT" ]] || die "advisor password grant failed"
# Prove the role landed: an advisor-only route must answer 200.
adv_status=$(curl -sS -o /dev/null -w '%{http_code}' "$API_URL/clients" -H "Authorization: Bearer $ADV_JWT")
[[ "$adv_status" == "200" ]] || die "advisor GET /clients → $adv_status (expected 200; role not effective)"
log "advisor authenticated + authorized (GET /clients → 200)"

# ── 3. traveler-linked client (POST /clients issues the invite → creates user) ─
# Must happen BEFORE the traveler auth user exists: Supabase refuses to invite an
# email that is already a user (502). On re-run the client already exists → skip.
# Wave F: GET /clients is a searchable {clients,…} envelope — ?q= matches email
# (and keeps the lookup honest now that the roster is paginated).
existing=$(curl -sS -G --data-urlencode "q=$TRV_EMAIL" "$API_URL/clients" -H "Authorization: Bearer $ADV_JWT" | python3 -c '
import json, sys
cs = json.load(sys.stdin)["clients"]
print(next((c["id"] for c in cs if c.get("email","").lower()==sys.argv[1].lower()), ""))' "$TRV_EMAIL")
if [[ -z "$existing" ]]; then
  body=$(python3 -c 'import json,sys; print(json.dumps({"full_name":"E2E Linked Traveler","email":sys.argv[1],"dossier":{"typed":{"contact_preference":"email","travel_party_notes":""}}}))' "$TRV_EMAIL")
  resp=$(curl -sS -w $'\n%{http_code}' -X POST "$API_URL/clients" \
    -H "Authorization: Bearer $ADV_JWT" -H 'content-type: application/json' -d "$body")
  code=$(printf '%s' "$resp" | tail -n1)
  cid=$(printf '%s' "$resp" | sed '$d' | python3 -c 'import json,sys; print(json.load(sys.stdin).get("client_id",""))' 2>/dev/null || true)
  [[ "$code" == 2* && -n "$cid" ]] || die "POST /clients → HTTP $code (invite/email send may have failed on staging SMTP)"
  log "created traveler-linked client $cid (owner: staging-advisor, email: $TRV_EMAIL)"
else
  log "traveler-linked client already exists ($existing)"
fi

# ── 4. traveler password + /me/client link (backfills auth_user_id + role) ────
TRV_UID=$(ensure_user "$TRV_EMAIL" "$TRV_PW")
TRV_JWT=$(grant "$TRV_EMAIL" "$TRV_PW")
[[ -n "$TRV_JWT" ]] || die "traveler password grant failed"
linked=$(curl -sS "$API_URL/me/client" -H "Authorization: Bearer $TRV_JWT" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin).get("client_id",""))')
[[ -n "$linked" ]] || die "traveler GET /me/client did not resolve a client"
log "traveler links to client $linked"

# ── 5. write the staging profiles into ~/.ovblack/.cli (passwords stay here) ──
ADV_EMAIL="$ADV_EMAIL" ADV_PW="$ADV_PW" TRV_EMAIL="$TRV_EMAIL" TRV_PW="$TRV_PW" \
API_URL="$API_URL" SUPABASE_URL="$SUPABASE_URL" ANON_KEY="$ANON_KEY" CLI="$CLI" \
python3 <<'PY'
import os, re
cli = os.environ["CLI"]
with open(cli) as fh:
    text = fh.read()

# Drop any existing staging / staging-advisor / staging-traveler sections so the
# rewrite is idempotent, preserving every other section + its comments.
def strip_section(text, name):
    pat = re.compile(rf"(?ms)^\[profile {re.escape(name)}\][^\[]*")
    return pat.sub("", text)

for name in ("staging", "staging-advisor", "staging-traveler"):
    text = strip_section(text, name)
text = text.rstrip() + "\n"

base = {
    "api_url": os.environ["API_URL"],
    "supabase_url": os.environ["SUPABASE_URL"],
    "auth_method": "password",
    "anon_key": os.environ["ANON_KEY"],
}
def block(name, email, pw, role):
    lines = [f"[profile {name}]"]
    for k, v in base.items():
        lines.append(f"{k} = {v}")
    lines.append(f"email = {email}")
    lines.append(f"password = {pw}")
    lines.append(f"role = {role}")
    return "\n".join(lines) + "\n"

adv_email, adv_pw = os.environ["ADV_EMAIL"], os.environ["ADV_PW"]
trv_email, trv_pw = os.environ["TRV_EMAIL"], os.environ["TRV_PW"]
text += "\n# ── staging e2e service users (provision-staging-users.sh) ──\n"
# Base `staging` profile defaults to the advisor identity for plain `--profile staging`.
text += block("staging", adv_email, adv_pw, "advisor")
text += block("staging-advisor", adv_email, adv_pw, "advisor")
text += block("staging-traveler", trv_email, trv_pw, "traveler")

with open(cli, "w") as fh:
    fh.write(text)
print("wrote staging / staging-advisor / staging-traveler profiles", flush=True)
PY

log "done — staging-advisor + staging-traveler ready. Run the e2e suite with:"
log "    cd apps/cli && OVB_PROFILE=staging uv run pytest -m e2e -q"
