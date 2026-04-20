#!/usr/bin/env bash
# Regenerate the TS client from apps/api's OpenAPI schema.
#
# Boots the FastAPI app in-process (via `uv run`), curls /openapi.json,
# shuts the server down, and hands the schema to @hey-api/openapi-ts.
# Running API is not required before invoking this — the script owns the
# whole boot/fetch/shutdown lifecycle.

set -euo pipefail

# Resolve paths relative to this script so `pnpm -C packages/api-client run
# generate` works from any CWD.
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PKG_DIR="$( cd "${SCRIPT_DIR}/.." && pwd )"
REPO_ROOT="$( cd "${PKG_DIR}/../.." && pwd )"
API_DIR="${REPO_ROOT}/apps/api"
OUT_DIR="${PKG_DIR}/src/generated"
SCHEMA_FILE="${PKG_DIR}/openapi.json"

PORT="${OV_BLACK_CODEGEN_PORT:-8765}"
BASE_URL="http://127.0.0.1:${PORT}"

# Guard: uv is the only Python runner for apps/api (T02 decision).
if ! command -v uv >/dev/null 2>&1; then
  echo "error: uv is not installed — see apps/api/pyproject.toml (T02)." >&2
  exit 1
fi

cleanup() {
  local exit_code=$?
  if [[ -n "${API_PID:-}" ]] && kill -0 "${API_PID}" 2>/dev/null; then
    kill "${API_PID}" 2>/dev/null || true
    # Give uvicorn a moment to flush, then hard-kill if still alive.
    for _ in 1 2 3 4 5; do
      kill -0 "${API_PID}" 2>/dev/null || break
      sleep 0.2
    done
    kill -9 "${API_PID}" 2>/dev/null || true
  fi
  rm -f "${SCHEMA_FILE}"
  exit "${exit_code}"
}
trap cleanup EXIT INT TERM

echo "→ Booting FastAPI on ${BASE_URL} to emit OpenAPI schema…"
pushd "${API_DIR}" >/dev/null
# Redirect server output so it doesn't interleave with codegen logs.
uv run uvicorn app.main:app \
  --host 127.0.0.1 \
  --port "${PORT}" \
  --log-level warning \
  >/tmp/ov-black-codegen-api.log 2>&1 &
API_PID=$!
popd >/dev/null

# Poll /health until the app is ready (cap at ~30s).
READY=0
for _ in $(seq 1 60); do
  if curl -fsS "${BASE_URL}/health" >/dev/null 2>&1; then
    READY=1
    break
  fi
  sleep 0.5
done

if [[ "${READY}" != "1" ]]; then
  echo "error: FastAPI did not become ready on ${BASE_URL}." >&2
  echo "----- server log -----" >&2
  cat /tmp/ov-black-codegen-api.log >&2 || true
  exit 1
fi

echo "→ Fetching ${BASE_URL}/openapi.json…"
curl -fsS "${BASE_URL}/openapi.json" -o "${SCHEMA_FILE}"

echo "→ Shutting API down before codegen…"
kill "${API_PID}" 2>/dev/null || true
wait "${API_PID}" 2>/dev/null || true
unset API_PID

echo "→ Regenerating TypeScript client into ${OUT_DIR#${REPO_ROOT}/}…"
rm -rf "${OUT_DIR}"
pushd "${PKG_DIR}" >/dev/null
# Config lives in openapi-ts.config.ts: input=./openapi.json, output=./src/generated,
# plugins=[@hey-api/client-fetch, @hey-api/sdk, @hey-api/typescript].
npx --no-install openapi-ts
popd >/dev/null

echo "✓ api-client generated."
