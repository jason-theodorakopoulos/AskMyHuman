#!/usr/bin/env bash
set -euo pipefail
set +x

if [[ $# != 1 || "$1" == --help || "$1" == -h ]]; then
  printf '%s\n' 'Usage: bash scripts/smoke_image.sh <locally-built-image>'
  exit 0
fi

IMAGE="$1"
NETWORK="askmyhuman-smoke-$$"
DATABASE="$NETWORK-db"
APPLICATION="$NETWORK-app"

fail() {
  printf 'image smoke failed: %s\n' "$1" >&2
  exit 1
}

cleanup() {
  timeout --kill-after=5 20 docker rm --force "$APPLICATION" "$DATABASE" >/dev/null 2>&1 || true
  timeout --kill-after=5 20 docker network rm "$NETWORK" >/dev/null 2>&1 || true
}

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
timeout --kill-after=5 15 docker image inspect "$IMAGE" >/dev/null 2>&1 || fail 'app image must already exist locally'
if ! timeout --kill-after=5 10 docker image inspect postgres:16-alpine >/dev/null 2>&1; then
  timeout --kill-after=5 120 docker pull postgres:16-alpine >/dev/null 2>&1 || fail 'PostgreSQL image unavailable'
fi
timeout --kill-after=5 15 docker network create --internal "$NETWORK" >/dev/null 2>&1 || fail 'network creation'
timeout --kill-after=5 30 docker run --detach --pull=never --name "$DATABASE" --network "$NETWORK" \
  --network-alias db -e POSTGRES_USER=smoke -e 'POSTGRES_PASSWORD=smoke@password%' \
  -e POSTGRES_DB=smoke postgres:16-alpine >/dev/null 2>&1 || fail 'database startup'

READY=false
for ((attempt=0; attempt<30; attempt++)); do
  [[ "$(timeout --kill-after=5 5 docker inspect --format '{{.State.Running}}' "$DATABASE" 2>/dev/null)" == true ]] || fail 'database exited'
  if timeout --kill-after=5 5 docker exec "$DATABASE" pg_isready -U smoke -d smoke >/dev/null 2>&1; then
    READY=true
    break
  fi
  sleep 1
done
[[ "$READY" == true ]] || fail 'database readiness deadline'

timeout --kill-after=5 30 docker run --detach --pull=never --name "$APPLICATION" --network "container:$DATABASE" \
  -e 'DATABASE_URL=postgresql+psycopg://smoke:smoke%40password%25@127.0.0.1:5432/smoke' \
  -e ACS_ENDPOINT=https://local.communication.azure.com \
  -e ACS_SOURCE_PHONE_NUMBER=+15555550100 -e MY_MOBILE_NUMBER=+15555550101 \
  -e AZURE_AI_ENDPOINT=https://local.cognitiveservices.azure.com \
  -e ACS_CALLBACK_AUDIENCE=smoke-immutable-resource-id \
  -e ACS_CALLBACK_URL=https://local.example.invalid/v1/callbacks/acs \
  -e ENTRA_TENANT_ID=00000000-0000-0000-0000-000000000000 \
  -e ENTRA_CLIENT_ID=00000000-0000-0000-0000-000000000000 \
  -e AUTHORIZED_AGENT_APP_IDS=00000000-0000-0000-0000-000000000000 \
  -e MCP_ALLOWED_HOSTS=127.0.0.1:8000,localhost:8000 \
  "$IMAGE" >/dev/null 2>&1 || fail 'application startup'

if ! timeout --kill-after=5 100 docker exec --interactive "$APPLICATION" python - <<'PY'
import asyncio
import base64
import json
import logging
import sys
import time

import httpx
import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

logging.disable(logging.CRITICAL)
origin = "http://127.0.0.1:8000"
stage = "readiness"


async def check_mcp() -> None:
  global stage
  stage = "MCP connection"
  principal = base64.b64encode(json.dumps({
    "auth_typ": "aad",
    "claims": [
      {"typ": "appid", "val": "00000000-0000-0000-0000-000000000000"},
      {"typ": "oid", "val": "isolated-smoke-agent"},
      {"typ": "roles", "val": "AskHuman.Invoke"},
    ],
  }).encode()).decode()
  async with httpx2.AsyncClient(
    headers={"x-ms-client-principal": principal}, timeout=10, trust_env=False,
  ) as client:
    async with streamable_http_client(origin + "/mcp", http_client=client) as streams:
      async with ClientSession(*streams) as session:
        stage = "MCP initialization"
        initialized = await session.initialize()
        assert initialized.capabilities.tools is not None
        stage = "MCP tools/list"
        tools = await session.list_tools()
        assert [tool.name for tool in tools.tools] == ["ask_human"]
        assert tools.tools[0].input_schema["type"] == "object"


try:
  deadline = time.monotonic() + 60
  with httpx.Client(base_url=origin, timeout=3, trust_env=False) as client:
    while True:
      try:
        if client.get("/health/ready").status_code == 200:
          break
      except httpx.TransportError:
        pass
      if time.monotonic() >= deadline:
        raise RuntimeError("readiness deadline")
      time.sleep(0.5)
    stage = "health"
    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").status_code == 200
    stage = "anonymous request rejection"
    assert client.post("/v1/requests", json={}).status_code == 401
    stage = "callback rejection"
    assert client.post(
      "/v1/callbacks/acs?token=IMAGE_SMOKE_QUERY_SENTINEL", json=[],
    ).status_code == 401
  asyncio.run(asyncio.wait_for(check_mcp(), timeout=20))
except BaseException as failure:
  print(f"image smoke failed at {stage}: {type(failure).__name__}; details suppressed", file=sys.stderr)
  raise SystemExit(1) from None
print("image health, authentication rejection and MCP initialization/tools-list passed")
PY
then
  timeout --kill-after=5 5 docker inspect --format 'runtime running={{.State.Running}} exit={{.State.ExitCode}}' "$APPLICATION" >&2 || true
  timeout --kill-after=5 5 docker logs "$APPLICATION" 2>&1 |
    grep -Eo '[A-Za-z_][A-Za-z0-9_]*(Error|Exception)' | sort -u >&2 || true
  fail 'HTTP/MCP checks or readiness deadline'
fi

VERSION="$(timeout --kill-after=5 10 docker exec "$DATABASE" psql -U smoke -d smoke -Atc 'select version_num from alembic_version' 2>/dev/null)" || fail 'migration query'
[[ "$VERSION" == 20260916_0002 ]] || fail 'migration revision mismatch'
ROWS="$(timeout --kill-after=5 10 docker exec "$DATABASE" psql -U smoke -d smoke -Atc 'select count(*) from human_requests' 2>/dev/null)" || fail 'request count query'
[[ "$ROWS" == 0 ]] || fail 'non-paid smoke unexpectedly created a human request'
LOGS="$(timeout --kill-after=5 10 docker logs "$APPLICATION" 2>&1)" || fail 'log capture'
[[ "$LOGS" != *IMAGE_SMOKE_QUERY_SENTINEL* && "$LOGS" != *smoke%40password%25* && "$LOGS" != *'smoke@password%'* ]] || fail 'sensitive sentinel appeared in runtime logs'
printf '%s\n' 'Image migration, runtime, health, MCP and log-privacy smoke passed; no calls made.'