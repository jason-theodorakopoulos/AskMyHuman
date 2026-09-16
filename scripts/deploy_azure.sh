#!/usr/bin/env bash
# Phase 5 Step 5.1 and 5.2: review, publish, deploy, and verify one immutable revision.
#
# Usage:
#   scripts/deploy_azure.sh what-if     # Review the deployment without changing Azure
#   scripts/deploy_azure.sh deploy      # Build the image, deploy Bicep, verify the revision
#   scripts/deploy_azure.sh verify      # Re-verify the current revision and auth boundaries
#
# Every value comes from the environment so no secret is ever committed or echoed.
set -euo pipefail

IMAGE_REPOSITORY="${IMAGE_REPOSITORY:-ask-my-human}"
REQUIRED_VARIABLES=(
  AZURE_RESOURCE_GROUP
  AZURE_LOCATION
  CONTAINER_REGISTRY_NAME
  CONTAINER_REGISTRY_SERVER
  CONTAINER_REGISTRY_RESOURCE_ID
  POSTGRES_ADMIN_PASSWORD
  MY_MOBILE_NUMBER
  ACS_SOURCE_PHONE_NUMBER
  ENTRA_TENANT_ID
  ENTRA_CLIENT_ID
  ENTRA_CLIENT_SECRET
  AUTHORIZED_AGENT_APP_IDS
  EXISTING_ACS_RESOURCE_ID
  ACS_CALLBACK_AUDIENCE
  MCP_ALLOWED_HOSTS
)

log() {
  printf '==> %s\n' "$1" >&2
}

fail() {
  printf 'error: %s\n' "$1" >&2
  exit 1
}

require_environment() {
  local missing=()
  local name
  for name in "${REQUIRED_VARIABLES[@]}"; do
    if [[ -z "${!name:-}" ]]; then
      missing+=("$name")
    fi
  done
  if ((${#missing[@]} > 0)); then
    fail "missing required environment variables: ${missing[*]}"
  fi
  command -v az >/dev/null || fail "the Azure CLI is required"
  command -v git >/dev/null || fail "git is required"
}

git_sha() {
  git rev-parse HEAD
}

resolve_image() {
  # The full commit SHA keeps the deployed image immutable and traceable.
  local sha
  sha="$(git_sha)"
  export CONTAINER_IMAGE="${CONTAINER_REGISTRY_SERVER}/${IMAGE_REPOSITORY}:${sha}"
}

deployment_name() {
  printf 'ask-my-human-%s' "$(git_sha | cut -c1-12)"
}

run_what_if() {
  log "Reviewing the deployment with what-if"
  az deployment group what-if \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --template-file infra/main.bicep \
    --parameters infra/environments/dev.bicepparam \
    --no-pretty-print >/dev/null
  log "what-if completed; rerun without --no-pretty-print to read the change list locally"
}

build_image() {
  log "Building ${IMAGE_REPOSITORY}:$(git_sha) in ${CONTAINER_REGISTRY_NAME}"
  az acr build \
    --registry "$CONTAINER_REGISTRY_NAME" \
    --image "${IMAGE_REPOSITORY}:$(git_sha)" \
    . >/dev/null
}

deploy_bicep() {
  log "Creating deployment $(deployment_name)"
  az deployment group create \
    --name "$(deployment_name)" \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --template-file infra/main.bicep \
    --parameters infra/environments/dev.bicepparam \
    --query 'properties.provisioningState' \
    --output tsv
}

container_app_name() {
  az deployment group show \
    --name "$(deployment_name)" \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --query properties.outputs.containerAppName.value \
    --output tsv
}

verify_revision() {
  local app="$1"
  local revision image active running
  revision="$(az containerapp show --name "$app" --resource-group "$AZURE_RESOURCE_GROUP" \
    --query properties.latestReadyRevisionName --output tsv)"
  [[ -n "$revision" ]] || fail "the container app has no ready revision"

  image="$(az containerapp revision show --name "$app" --resource-group "$AZURE_RESOURCE_GROUP" \
    --revision "$revision" --query 'properties.template.containers[0].image' --output tsv)"
  active="$(az containerapp revision show --name "$app" --resource-group "$AZURE_RESOURCE_GROUP" \
    --revision "$revision" --query 'properties.active' --output tsv)"
  running="$(az containerapp revision show --name "$app" --resource-group "$AZURE_RESOURCE_GROUP" \
    --revision "$revision" --query 'properties.runningState' --output tsv)"

  log "Ready revision ${revision} (active=${active}, runningState=${running})"
  [[ "$image" == "$CONTAINER_IMAGE" ]] || fail "revision image ${image} is not the reviewed ${CONTAINER_IMAGE}"
  [[ "$active" == "true" ]] || fail "revision ${revision} is not active"
  [[ "$running" == "Running" ]] || fail "revision ${revision} is not running"
}

verify_authentication_boundary() {
  local base_url="$1"
  local status
  local invalid_authorization="Bearer invalid-callback-token"

  status="$(curl -s -o /dev/null -w '%{http_code}' -X POST "${base_url}/v1/requests" \
    -H 'content-type: application/json' \
    -d '{"kind":"approval","prompt":"smoke","idempotencyKey":"00000000-0000-4000-8000-000000000000"}')"
  [[ "$status" == "401" || "$status" == "403" ]] || fail "/v1/requests accepted an unauthenticated caller (${status})"

  status="$(curl -s -o /dev/null -w '%{http_code}' -X POST "${base_url}/mcp" \
    -H 'content-type: application/json' -H 'accept: application/json, text/event-stream' \
    -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}')"
  [[ "$status" == "401" || "$status" == "403" ]] || fail "/mcp accepted an unauthenticated caller (${status})"

  status="$(curl -s -o /dev/null -w '%{http_code}' -X POST "${base_url}/v1/callbacks/acs" \
    -H 'content-type: application/json' -H "authorization: ${invalid_authorization}" \
    -d '[]')"
  [[ "$status" == "401" ]] || fail "the ACS callback accepted an invalid token (${status})"

  status="$(curl -s -o /dev/null -w '%{http_code}' "${base_url}/health/live")"
  log "Authentication boundary verified; /health/live returned ${status}"
}

service_url() {
  local app="$1"
  local fqdn
  fqdn="$(az containerapp show --name "$app" --resource-group "$AZURE_RESOURCE_GROUP" \
    --query properties.configuration.ingress.fqdn --output tsv)"
  printf 'https://%s' "$fqdn"
}

main() {
  local command="${1:-deploy}"
  require_environment
  resolve_image

  case "$command" in
    what-if)
      run_what_if
      ;;
    deploy)
      run_what_if
      build_image
      deploy_bicep
      local app
      app="$(container_app_name)"
      verify_revision "$app"
      verify_authentication_boundary "$(service_url "$app")"
      log "Deployment verified. Live calls may now run against $(service_url "$app")"
      ;;
    verify)
      local existing
      existing="$(container_app_name)"
      verify_revision "$existing"
      verify_authentication_boundary "$(service_url "$existing")"
      ;;
    *)
      fail "unknown command: ${command}"
      ;;
  esac
}

main "$@"
