#!/usr/bin/env bash
set -euo pipefail
set +x
umask 077

usage() {
  printf '%s\n' \
    'Usage: deploy_azure.sh {help|what-if [rollback]|publish|deploy|verify|rollback}' \
    'No command defaults to help. This script never logs in or authorizes paid calls.' \
    '1. Set SOURCE_SHA to the reviewed clean HEAD and explicit subscription/RG/app/registry.' \
    '2. With CONTAINER_IMAGE unset, run what-if to review the publication preview.' \
    '3. Obtain an external MUTATION_APPROVAL_FILE, then publish; retain its JSON build record.' \
    '4. Set BUILD_RECORD_FILE and CONTAINER_IMAGE to that pushed digest. Run what-if again.' \
    '5. Obtain a new MUTATION_APPROVAL_FILE for the exact binding, then deploy.' \
    '6. verify requires EXPECTED_REVISION, SERVICE_URL, HEALTH_BEARER_TOKEN, RELEASE_APPROVAL_FILE,' \
    '   REVIEWED_PARAMETERS_SHA256 and REVIEWED_WHAT_IF_SHA256 from the approved what-if binding.' \
    'Approval JSON: {record, approver, expires_at (UTC ISO8601), binding: <what-if binding>}.' \
    'Release approval also requires decisions.DR-01 through DR-05, each a record ID.' \
    'Release binding adds revision and endpoint. Approvals come from the external release owner.' \
    'Rollback: select a previously approved digest and PREVIOUS_RELEASE_APPROVAL_FILE;' \
    'run what-if rollback, obtain fresh mutation approval, then rollback. Never rebuild.' \
    'Use VERIFY_OPERATION=rollback to reverify a rollback with its approval binding.' \
    'A failed first deployment stays release-blocked; an operator must review recovery.'
}

fail() {
  printf 'error: %s\n' "$1" >&2
  exit 1
}

require_variables() {
  local variable
  for variable in "$@"; do
    [[ -n "${!variable:-}" ]] || fail "missing required variable: $variable"
  done
}

azure() {
  local limit="${AZURE_COMMAND_TIMEOUT_SECONDS:-120}"
  [[ "$limit" =~ ^[1-9][0-9]{0,3}$ ]] && ((limit <= 3600)) || fail 'invalid Azure command timeout'
  if [[ -n "${VERIFY_DEADLINE:-}" ]]; then
    limit=$((VERIFY_DEADLINE - SECONDS))
    ((limit > 0)) || fail 'revision verification deadline exhausted'
    ((limit <= 30)) || limit=30
  fi
  timeout --kill-after=5 "$limit" az "$@" --subscription "$AZURE_SUBSCRIPTION_ID" \
    --only-show-errors 2>/dev/null || fail 'Azure command failed or timed out; release blocked'
}

hash_json() {
  jq -cS . | sha256sum | cut -d ' ' -f 1
}

check_source() {
  [[ "$SOURCE_SHA" =~ ^[0-9a-f]{40}$ ]] || fail 'SOURCE_SHA must be the reviewed full Git SHA'
  [[ "$(git rev-parse HEAD)" == "$SOURCE_SHA" ]] || fail 'reviewed source does not match HEAD'
  [[ -z "$(git status --porcelain --untracked-files=all)" ]] || fail 'source is dirty or contains untracked files'
}

check_image() {
  local prefix="$CONTAINER_REGISTRY_SERVER/$IMAGE_REPOSITORY@sha256:"
  [[ "$CONTAINER_IMAGE" == "$prefix"* ]] || fail 'image must use the approved registry/repository digest'
  local digest="${CONTAINER_IMAGE#"$prefix"}"
  [[ "$digest" =~ ^[0-9a-f]{64}$ ]] || fail 'image digest is invalid'
}

initialize() {
  IMAGE_REPOSITORY="${IMAGE_REPOSITORY:-ask-my-human}"
  require_variables SOURCE_SHA AZURE_SUBSCRIPTION_ID AZURE_RESOURCE_GROUP CONTAINER_APP_NAME \
    CONTAINER_REGISTRY_NAME CONTAINER_REGISTRY_SERVER CONTAINER_REGISTRY_RESOURCE_ID
  local tool
  for tool in az git jq timeout curl sha256sum tar mktemp; do
    command -v "$tool" >/dev/null || fail "required tool unavailable: $tool"
  done
  [[ "$AZURE_SUBSCRIPTION_ID" =~ ^[0-9a-fA-F-]{36}$ ]] || fail 'invalid subscription ID'
  [[ "$AZURE_RESOURCE_GROUP" =~ ^[a-zA-Z0-9_.-]+$ ]] || fail 'invalid resource group'
  [[ "$CONTAINER_APP_NAME" =~ ^[a-z][a-z0-9-]{0,30}[a-z0-9]$ ]] || fail 'invalid Container App name'
  [[ "$CONTAINER_REGISTRY_NAME" =~ ^[a-zA-Z0-9]+$ ]] || fail 'invalid registry name'
  [[ "$CONTAINER_REGISTRY_SERVER" =~ ^[a-zA-Z0-9.-]+$ ]] || fail 'invalid registry server'
  [[ "$IMAGE_REPOSITORY" =~ ^[a-z0-9][a-z0-9._/-]*$ ]] || fail 'invalid image repository'
  check_source
}

deployment_environment() {
  require_variables AZURE_LOCATION POSTGRES_ADMIN_PASSWORD MY_MOBILE_NUMBER ACS_SOURCE_PHONE_NUMBER \
    ENTRA_TENANT_ID ENTRA_CLIENT_ID ENTRA_CLIENT_SECRET AUTHORIZED_AGENT_APP_IDS \
    EXISTING_ACS_RESOURCE_ID ACS_CALLBACK_AUDIENCE ACS_CALLBACK_URL MCP_ALLOWED_HOSTS
  [[ "$ACS_CALLBACK_URL" =~ ^https://[a-zA-Z0-9.-]+(:443)?/v1/callbacks/acs$ ]] || fail 'callback URL must be the full HTTPS endpoint'
  [[ "$ACS_CALLBACK_AUDIENCE" != *://* && "$ACS_CALLBACK_AUDIENCE" != /subscriptions/* ]] || fail 'callback audience must be the verified ACS immutable resource ID'
  PARAMETERS_SHA256="$(jq -n '[env | {AZURE_LOCATION, CONTAINER_REGISTRY_SERVER,
    CONTAINER_REGISTRY_RESOURCE_ID, POSTGRES_ADMIN_PASSWORD, MY_MOBILE_NUMBER,
    ACS_SOURCE_PHONE_NUMBER, ENTRA_TENANT_ID, ENTRA_CLIENT_ID, ENTRA_CLIENT_SECRET,
    AUTHORIZED_AGENT_APP_IDS, EXISTING_ACS_RESOURCE_ID, ACS_CALLBACK_AUDIENCE,
    ACS_CALLBACK_URL, MCP_ALLOWED_HOSTS}]' | hash_json)"
}

prepare_image() {
  OPERATION=deploy
  if [[ "$COMMAND" == publish || ( "$COMMAND" == what-if && -z "${CONTAINER_IMAGE:-}" ) ]]; then
    [[ -z "${CONTAINER_IMAGE:-}" ]] || fail 'publish forbids CONTAINER_IMAGE overrides'
    OPERATION=publish
    CONTAINER_IMAGE="$CONTAINER_REGISTRY_SERVER/$IMAGE_REPOSITORY:$SOURCE_SHA"
    REVISION_SUFFIX="${SOURCE_SHA:0:12}-preview"
  else
    require_variables CONTAINER_IMAGE
    check_image
    local digest="${CONTAINER_IMAGE##*@sha256:}"
    REVISION_SUFFIX="${SOURCE_SHA:0:12}-${digest:0:12}"
    if [[ "$COMMAND" == rollback || "${2:-}" == rollback || ( "$COMMAND" == verify && "${VERIFY_OPERATION:-deploy}" == rollback ) ]]; then
      OPERATION=rollback
      require_variables PREVIOUS_RELEASE_APPROVAL_FILE
      jq -e --arg image "$CONTAINER_IMAGE" --arg app "$CONTAINER_APP_NAME" \
        --arg subscription "$AZURE_SUBSCRIPTION_ID" --arg group "$AZURE_RESOURCE_GROUP" '
        (.record | type == "string" and length > 0) and
        (.approver | type == "string" and length > 0) and
        .binding.image == $image and .binding.app == $app and
        .binding.subscription == $subscription and .binding.resource_group == $group and
        (.decisions as $decisions | all(["DR-01", "DR-02", "DR-03", "DR-04", "DR-05"][];
          $decisions[.] | type == "string" and length > 0))
      ' "$PREVIOUS_RELEASE_APPROVAL_FILE" >/dev/null 2>&1 || fail 'previous release approval does not match rollback target'
    else
      require_variables BUILD_RECORD_FILE
      jq -e --arg image "$CONTAINER_IMAGE" --arg source "$SOURCE_SHA" '
        .source_sha == $source and .image == $image and .source == "az acr build"
      ' "$BUILD_RECORD_FILE" >/dev/null 2>&1 || fail 'build record does not bind the image to reviewed source'
    fi
  fi
  export CONTAINER_IMAGE REVISION_SUFFIX CONTAINER_APP_NAME
}

binding() {
  jq -n --arg operation "$OPERATION" --arg source_sha "$SOURCE_SHA" \
    --arg subscription "$AZURE_SUBSCRIPTION_ID" --arg resource_group "$AZURE_RESOURCE_GROUP" \
    --arg app "$CONTAINER_APP_NAME" --arg registry "$CONTAINER_REGISTRY_NAME" \
    --arg registry_server "$CONTAINER_REGISTRY_SERVER" --arg repository "$IMAGE_REPOSITORY" \
    --arg image "$CONTAINER_IMAGE" --arg parameters_sha256 "$PARAMETERS_SHA256" \
    --arg what_if_sha256 "$WHAT_IF_SHA256" \
    '{operation:$operation, source_sha:$source_sha, subscription:$subscription,
      resource_group:$resource_group, app:$app, registry:$registry,
      registry_server:$registry_server, repository:$repository, image:$image,
      parameters_sha256:$parameters_sha256, what_if_sha256:$what_if_sha256}'
}

what_if() {
  local result summary
  result="$(AZURE_COMMAND_TIMEOUT_SECONDS="${WHAT_IF_TIMEOUT_SECONDS:-900}" \
    azure deployment group what-if --resource-group "$AZURE_RESOURCE_GROUP" \
    --template-file infra/main.bicep --parameters infra/environments/dev.bicepparam \
    --no-pretty-print --output json)"
  summary="$(printf '%s' "$result" | jq -ce '
    def changes: if has("changes") then .changes else .properties.changes end;
    if .status != "Succeeded" or (changes | type != "array") then error("invalid what-if") else
      [changes[] | {
        resource_id: (.resourceId | if type == "string" and test("^/subscriptions/[A-Za-z0-9/_.() -]+$")
          then . else error("invalid resource ID") end),
        resource_type: (.resourceId | split("/providers/") | last | split("/") |
          [to_entries[] | select(.key == 0 or .key % 2 == 1) | .value] | join("/")),
        change: (.changeType | if IN("Create", "Delete", "Modify", "NoChange", "Ignore", "Deploy")
          then . else error("unsupported change") end),
        property_paths: [(.delta // []) | .. | objects | select(has("propertyChangeType")) |
          .path? // empty |
          select(type == "string" and test("^[A-Za-z0-9_.\\[\\]-]+$"))] | unique
      }] | sort_by(.resource_id)
    end' 2>/dev/null)" || fail 'malformed what-if metadata'
  WHAT_IF_SHA256="$(printf '%s' "$result" | jq -cS '
    (if has("changes") then .changes else .properties.changes end) | sort_by(.resourceId)
  ' | hash_json)"
  BINDING="$(binding)"
  local review
  review="$(jq -n --argjson binding "$BINDING" --argjson changes "$summary" \
    '{binding:$binding, changes:$changes}')"
  if [[ "$COMMAND" == what-if ]]; then
    printf '%s\n' "$review"
  else
    printf '%s\n' "$review" >&2
  fi
}

approval() {
  local file="$1" expected="$2"
  jq -e --argjson binding "$expected" '
    .binding == $binding and (.record | type == "string" and length > 0) and
    (.approver | type == "string" and length > 0) and
    (.expires_at | fromdateiso8601) > now
  ' "$file" >/dev/null 2>&1 || fail 'external approval missing, expired or mismatched'
}

publish() {
  local result digest
  check_source
  SNAPSHOT="$(mktemp -d)"
  trap 'rm -rf -- "$SNAPSHOT"' EXIT
  git archive "$SOURCE_SHA" | tar -x -C "$SNAPSHOT"
  check_source
  result="$(timeout --kill-after=5 900 az acr build --registry "$CONTAINER_REGISTRY_NAME" \
    --subscription "$AZURE_SUBSCRIPTION_ID" --image "$IMAGE_REPOSITORY:$SOURCE_SHA" \
    --file Dockerfile --no-logs --only-show-errors --output json "$SNAPSHOT" 2>/dev/null)" || fail 'image publication failed or timed out'
  digest="$(printf '%s' "$result" | jq -er --arg registry "$CONTAINER_REGISTRY_SERVER" \
    --arg repository "$IMAGE_REPOSITORY" --arg tag "$SOURCE_SHA" '
    select(.status == "Succeeded") | .outputImages | select(length == 1) | .[0] |
    select(.registry == $registry and .repository == $repository and .tag == $tag) |
    .digest | select(test("^sha256:[0-9a-f]{64}$"))' 2>/dev/null)" || fail 'build did not return a unique immutable pushed digest'
  jq -n --arg source_sha "$SOURCE_SHA" \
    --arg image "$CONTAINER_REGISTRY_SERVER/$IMAGE_REPOSITORY@$digest" \
    '{source:"az acr build", source_sha:$source_sha, image:$image}'
  rm -rf -- "$SNAPSHOT"
  trap - EXIT
}

http_status() {
  curl --silent --output /dev/null --write-out '%{http_code}' --connect-timeout 5 \
    --max-time 15 --proto '=https' "$@" 2>/dev/null || fail 'HTTP check failed or timed out'
}

verify_authentication() {
  local path status
  require_variables HEALTH_BEARER_TOKEN
  [[ "$HEALTH_BEARER_TOKEN" =~ ^[a-zA-Z0-9._~-]+$ ]] || fail 'invalid health bearer token format'
  for path in /v1/requests /mcp /health/live /health/ready; do
    status="$(http_status "$SERVICE_URL$path")"
    [[ "$status" == 401 || "$status" == 403 ]] || fail 'protected endpoint accepted an anonymous request'
  done
  status="$(http_status -X POST "$SERVICE_URL/v1/callbacks/acs" \
    -H 'content-type: application/json' -H 'authorization: Bearer invalid-callback-token' -d '[]')"
  [[ "$status" == 401 ]] || fail 'callback did not reject invalid authorization'
  for path in /health/live /health/ready; do
    status="$(jq -nr '"header = " + ("Authorization: Bearer " + env.HEALTH_BEARER_TOKEN | tojson)' |
      http_status --config - "$SERVICE_URL$path")"
    [[ "$status" == 200 ]] || fail 'authenticated health check failed'
  done
}

verify_revision() {
  local app revision ready=false limit="${VERIFY_TIMEOUT_SECONDS:-300}"
  [[ "$limit" =~ ^[1-9][0-9]{0,2}$ ]] || fail 'verification timeout must be 1..600 seconds'
  ((limit <= 600)) || fail 'verification timeout must be 1..600 seconds'
  VERIFY_DEADLINE=$((SECONDS + limit))
  for ((attempt=0; attempt<60 && SECONDS<VERIFY_DEADLINE; attempt++)); do
    app="$(azure containerapp show --name "$CONTAINER_APP_NAME" --resource-group "$AZURE_RESOURCE_GROUP" --output json)"
    revision="$(azure containerapp revision show --name "$CONTAINER_APP_NAME" \
      --resource-group "$AZURE_RESOURCE_GROUP" --revision "$EXPECTED_REVISION" --output json)"
    printf '%s' "$app" | jq -e --arg revision "$EXPECTED_REVISION" --arg endpoint "$SERVICE_URL" '
      .properties.latestRevisionName == $revision and
      ("https://" + .properties.configuration.ingress.fqdn) == $endpoint and
      .properties.configuration.activeRevisionsMode == "Single"
    ' >/dev/null 2>&1 || fail 'current revision or endpoint differs from the approved target'
    printf '%s' "$revision" | jq -e --arg image "$CONTAINER_IMAGE" --arg revision "$EXPECTED_REVISION" '
      .name == $revision and (.properties.template.containers | length == 1) and
      .properties.template.containers[0].image == $image
    ' >/dev/null 2>&1 || fail 'intended revision does not run the expected immutable image'
    if printf '%s' "$revision" | jq -e '
        .properties.active == true and .properties.runningState == "Running" and
        .properties.healthState == "Healthy" and .properties.provisioningState == "Provisioned"
      ' >/dev/null 2>&1 && printf '%s' "$app" | jq -e --arg revision "$EXPECTED_REVISION" '
        .properties.latestReadyRevisionName == $revision and
        ([.properties.configuration.ingress.traffic[] |
          select(.weight > 0) | select(.revisionName == $revision or .latestRevision == true) |
          .weight] | add) == 100 and
        ([.properties.configuration.ingress.traffic[].weight] | add) == 100
      ' >/dev/null 2>&1; then
      ready=true
      break
    fi
    ((SECONDS + 2 < VERIFY_DEADLINE)) || break
    sleep 2
  done
  [[ "$ready" == true ]] || fail 'intended revision did not become active, Running, Healthy and ready before deadline'
  unset VERIFY_DEADLINE
}

verify() {
  require_variables EXPECTED_REVISION SERVICE_URL RELEASE_APPROVAL_FILE HEALTH_BEARER_TOKEN
  [[ "$SERVICE_URL" =~ ^https://[a-zA-Z0-9.-]+$ ]] || fail 'service endpoint must be an HTTPS origin'
  [[ "$EXPECTED_REVISION" == "$CONTAINER_APP_NAME--$REVISION_SUFFIX" ]] || fail 'revision must match the reviewed source and digest'
  local release_binding
  release_binding="$(printf '%s' "$BINDING" | jq --arg revision "$EXPECTED_REVISION" \
    --arg endpoint "$SERVICE_URL" '. + {revision:$revision, endpoint:$endpoint}')"
  approval "$RELEASE_APPROVAL_FILE" "$release_binding"
  jq -e '.decisions as $decisions | all(["DR-01", "DR-02", "DR-03", "DR-04", "DR-05"][];
    $decisions[.] | type == "string" and length > 0)' \
    "$RELEASE_APPROVAL_FILE" >/dev/null 2>&1 || fail 'external DR-01 through DR-05 decisions are required'
  verify_revision
  verify_authentication
  verify_revision
  jq -n --arg image "$CONTAINER_IMAGE" --arg revision "$EXPECTED_REVISION" \
    --arg endpoint "$SERVICE_URL" --arg source_sha "$SOURCE_SHA" \
    '{source:"az containerapp revision show", captured_at:(now | todateiso8601),
      source_sha:$source_sha, image:$image, revision:$revision, endpoint:$endpoint,
      active:true, running_state:"Running", health_state:"Healthy", ready:true,
      traffic_percent:100, authentication_verified:true, paid_calls_authorized:false}'
}

main() {
  COMMAND="${1:-help}"
  case "$COMMAND" in
    help|--help|-h) usage; return ;;
    what-if|publish|deploy|verify|rollback) ;;
    *) fail 'unknown command; use help' ;;
  esac
  (($# <= 2)) || fail 'unexpected arguments'
  [[ -z "${2:-}" || ( "$COMMAND" == what-if && "$2" == rollback ) ]] || fail 'unexpected argument'
  initialize
  if [[ "$COMMAND" == verify ]]; then
    require_variables REVIEWED_WHAT_IF_SHA256 REVIEWED_PARAMETERS_SHA256
    [[ "$REVIEWED_WHAT_IF_SHA256" =~ ^[0-9a-f]{64}$ && "$REVIEWED_PARAMETERS_SHA256" =~ ^[0-9a-f]{64}$ ]] || fail 'invalid reviewed fingerprints'
    PARAMETERS_SHA256="$REVIEWED_PARAMETERS_SHA256"
  else
    deployment_environment
  fi
  prepare_image "$@"
  if [[ "$COMMAND" == verify ]]; then
    WHAT_IF_SHA256="$REVIEWED_WHAT_IF_SHA256"
    BINDING="$(binding)"
    verify
    return
  fi
  if [[ "$COMMAND" != what-if ]]; then
    require_variables MUTATION_APPROVAL_FILE
  fi
  what_if
  [[ "$COMMAND" != what-if ]] || return 0
  approval "$MUTATION_APPROVAL_FILE" "$BINDING"
  check_source
  if [[ "$COMMAND" == publish ]]; then
    publish
  else
    local result
    result="$(AZURE_COMMAND_TIMEOUT_SECONDS="${DEPLOY_TIMEOUT_SECONDS:-3600}" \
      azure deployment group create --name "askmyhuman-$REVISION_SUFFIX" \
      --resource-group "$AZURE_RESOURCE_GROUP" --template-file infra/main.bicep \
      --parameters infra/environments/dev.bicepparam --output json)"
    printf '%s' "$result" | jq -e --arg app "$CONTAINER_APP_NAME" '
      .properties.provisioningState == "Succeeded" and .properties.outputs.containerAppName.value == $app
    ' >/dev/null 2>&1 || fail 'deployment did not succeed for the approved app'
    EXPECTED_REVISION="$CONTAINER_APP_NAME--$REVISION_SUFFIX"
    verify
  fi
}

main "$@"
