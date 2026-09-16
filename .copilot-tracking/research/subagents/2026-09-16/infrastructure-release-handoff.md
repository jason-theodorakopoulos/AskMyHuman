---
title: Infrastructure and Release Correction Handoff
description: Evidence and implementation guidance for the assigned infrastructure and release findings.
ms.date: 2026-09-16
---

## Status and Scope

Status: Complete research; implementation blocked by active mode.
Researcher Subagent mode permits research documentation,
not implementation changes. Product corrections requested by the parent remain
unimplemented by this session. No environment files or secrets are accessed.

Assigned surfaces: infra/**, scripts/deploy_azure.sh, Dockerfile, compose.yaml,
.github/workflows/ci.yml, .dockerignore, and optional focused deploy regression
and image smoke files. Preserve public endpoints and the sole callback auth
exclusion. No deployment, publication, or live calls are authorized.

## Questions

* How must callback audience and callback URL be separated in infrastructure?
* Which settings enforce effective 30-day Application Insights table retention?
* Can public evidence establish the exact configured ACS role GUID?
* Which release checks bind approval, source, immutable image, target and health?
* Which image, Compose and CI corrections support a bounded non-live smoke?

## Initial Evidence

* Finalized review 002 confirms audience/URL conflation and missing explicit
  Application Insights table retention. The audience is ACS immutableResourceId,
  not its ARM resource path.
* Finalized review 004 confirms default access logging, mutable Python base tags,
  Compose host/exposure problems and missing runtime image smoke.
* scripts/deploy_azure.sh defaults to deploy, suppresses what-if output, builds
  the current dirty directory under HEAD's tag, optionally trusts CONTAINER_IMAGE,
  checks latestReadyRevisionName without healthState and performs anonymous health.

## Current Shared Workspace

The shared workspace changed after the finalized reviews. These changes were
observed, not made by this researcher, and must not be reverted or credited to
this session:

* Dockerfile already pins both Python stages to the digest verified below and
  sets `--workers 1 --no-access-log`.
* compose.yaml already binds both ports to 127.0.0.1 and uses
  `MCP_ALLOWED_HOSTS: localhost:8000,127.0.0.1:8000`.
* tests/integration/test_asgi_app.py contains a new image regression using
  `smoke@password%`, migrations, both health routes and query-log redaction.
  At read time its environment still used the old audience-as-URL setting and
  had no callback URL; coordinate the new required setting with that owner.
  Its image test has no MCP initialization or tools-list check yet.

## Infrastructure Corrections

### Separate Callback Destination and JWT Audience

Add `acsCallbackUrl` to infra/main.bicep and
infra/modules/container-app.bicep, forward it in the root module invocation,
and bind it to `ACS_CALLBACK_URL` in the container environment. Read
`ACS_CALLBACK_URL` in infra/environments/dev.bicepparam and require it in the
deployment script. The URL is a complete HTTPS endpoint including
`/v1/callbacks/acs`; do not append the route a second time.

Keep `acsCallbackAudience` as a distinct nonempty resource identifier string.
Correct the root description, which currently calls it a public service URL.
The finalized review identifies ACS `properties.immutableResourceId` as the
intended value, not the `/subscriptions/...` ARM ID. The public webhook guide
requires the audience value from the JWT and links the ACS resource-ID guide.
An explicit verified input is compatible with the user-requested contract;
automatic derivation from the existing resource is optional, not necessary.

Update Compose and CI placeholders to a dummy nonempty audience and a full
HTTPS callback URL such as `https://placeholder.example.com/v1/callbacks/acs`.
These are validation placeholders, not reachable callback endpoints. Preserve
all approved public network settings and exclude only `/v1/callbacks/acs` from
Entra authentication. Never exempt health or metadata for script convenience.

### Effective Telemetry Retention

infra/modules/observability.bicep currently sets workspace and component
retention to 30 but defines no workspace table resources. Add explicit table
configuration for the Application Insights tables, with both
`retentionInDays: 30` and `totalRetentionInDays: 30`. Cover AppRequests,
AppDependencies, AppTraces, AppMetrics and other enabled App telemetry tables
such as AppExceptions, AppEvents, AppAvailabilityResults, AppPageViews,
AppBrowserTimings and AppPerformanceCounters. Confirm the enabled inventory
against the target workspace before claiming effective retention.

Use `Microsoft.OperationalInsights/workspaces/tables@2023-09-01`, parented to
the workspace, and explicitly order changes after the workspace-based
Application Insights component. Do not create custom schemas to impersonate
standard App tables. Whether component creation has provisioned every table
when these updates run remains a resource-provider acceptance check.

The workspace schema exposes `properties.features.immediatePurgeDataOn30Days`.
Set it to true for the strict 30-day policy, but retain a verification gate:
the retention guide says the operation is supported by Workspaces Update API.
Schema acceptance and Bicep compilation do not prove deployed purge behavior.
Preserve public ingestion/query access and avoid introducing archive retention.
Usage/AzureActivity exceptions and PostgreSQL backups still need policy approval.

### ACS Role Identity

The exact GUID is `0d8b7e87-0907-4e9d-a49d-ad2166c4bf2e` in
infra/modules/communications-acs-role-assignment.bicep. Public Microsoft
built-in-role index and ACS authentication documentation did not identify it.
Guessed communication/other role-category URLs returned 404; those results
are not evidence that the GUID is nonexistent or that a replacement is valid.

Leave the role unchanged without authoritative evidence. Ask the target
subscription owner for a sanitized definition showing name, type, actions,
dataActions, exclusions and assignable scopes. Compare permissions with
create-call, recognize, play and hang-up. Do not substitute Owner/Contributor
or invent custom actions. Authentication documentation confirms Entra support
for Call Automation but does not establish this role's permissions.

## Release Corrections

### Approval and Provenance

* Default to usage/help without environment requirements or external commands.
  Require an explicit mutation subcommand and separate recorded mutation and
  release approvals; the presence of deployment secrets is not approval.
* Bind approvals to the reviewed source SHA, explicit subscription/resource
  group/app target, registry/repository, sanitized parameter fingerprint and
  reviewed what-if fingerprint. For final release bind the exact image digest,
  revision and service endpoint as well. Changed bindings must fail closed.
* What-if must show a reviewable resource/action summary, not discarded output.
  Parse JSON and allowlist resource IDs/types, change kinds and changed property
  paths. Do not retain raw parameter values, before/after secret values, phone
  numbers, arbitrary diagnostic messages or raw deployment errors as artifacts.
* Check clean source before publication, including untracked build inputs.
  Prefer building a reviewed Git snapshot if concurrent workspace changes could
  race a cleanliness check. Never label a dirty directory with HEAD's SHA.
* Normal build/deploy must reject stale `CONTAINER_IMAGE` overrides. Resolve
  the resulting ACR manifest digest and deploy `registry/repository@sha256:...`.
  A SHA-shaped mutable tag alone is not content addressing.
* Rollback is separate from normal publication: select a previously approved
  digest and do not rebuild current source. Help can state the operator steps
  and first-deployment blocked-release outcome without adding a rollback mode.

### Intended Revision and Authentication

Release verification must require an expected digest and intended revision.
After deployment, capture the intended latest revision, not only
`latestReadyRevisionName`, which can still identify an older revision.
Poll within a finite deadline until that revision is ready, active, Running
and Healthy and its container image exactly matches the expected digest.
Verify the app traffic/ready state still targets that revision. Verification
must not silently become a diagnostic report of whichever image happens to run.

Use an approved bearer token for public `/health/live` and `/health/ready`,
keeping every public health request behind Entra. Do not use a forged
`x-ms-client-principal` header as public auth proof. Keep anonymous HTTP/MCP
rejection and invalid ACS token rejection checks. Apply curl connect and
overall timeouts and bound readiness polling and Azure metadata commands.
Avoid printing token-bearing commands or response bodies. Failure blocks
release and emits only sanitized status and rollback instructions.

Do not announce that live calls may now run solely because smoke checks pass.
DR-01 through DR-05 and the separate paid-call consent remain required, and
the parent live harness must consume the bound release evidence.

### Focused Stub Regression Matrix

Use the permitted tests/unit/test_deploy_script.py with temporary executable
Git/Azure/curl stubs and dummy credentials only. No real Azure CLI invocation
or mutation is needed. Cover:

* No arguments/help executes no external commands.
* Missing or mismatched source/target/what-if approval prevents publication.
* Dirty tracked or included untracked input and stale image override fail.
* A what-if deletion is visible in sanitized output; dummy secret values are not.
* The pushed digest is the digest passed to Bicep and revision verification.
* Old ready revision, wrong digest, inactive or unhealthy revision fail.
* Healthy intended revision, negative auth checks and bearer-authenticated
  health succeed while anonymous health remains rejected.
* Missing token, failed health, malformed metadata and deadline exhaustion fail.
* Curl and metadata calls have bounded execution; failed checks never emit a
  release-success record or trigger live commands.

## Image and CI Corrections

### Verified Base Digest

Public Docker registry lookup on 2026-09-16 returned:

```text
python:3.12-slim-bookworm
sha256:782412e85d0f0984994c290652577d4018aff08145c85b262bb63dc0c7522254
mediaType: application/vnd.oci.image.index.v1+json
```

Both lookup by tag and lookup by digest returned that same digest. The manifest
index includes Linux amd64 and arm64/v8, among other platforms. The current
Dockerfile already uses it in both stages. This verifies existence and tag
resolution, not image startup or vulnerability posture. No layers were pulled
by this registry metadata check.

### Bounded Non-Live Smoke

The image job currently builds with `push: false` and `load: false`, and never
runs the built image. Load and tag the local result, then call the one permitted
smoke shell script. Do not publish. Set a job/step timeout as an outer bound.

Use an isolated Docker network containing only app and throwaway PostgreSQL,
preferably internal to prevent outbound Azure connectivity. Start the normal
image command so Alembic runs before Uvicorn. Use a dummy database password
containing `@` and `%` with its correctly encoded DSN to exercise the parent
migration correction. Bind published test ports only to loopback. Include the
new callback URL and audience separately and disable external telemetry setup
by leaving real telemetry/credential variables absent.

Wait for PostgreSQL and app readiness within a deadline; fail immediately on
container exit. Verify the Alembic revision in PostgreSQL, both health routes,
anonymous request rejection, missing-token callback rejection and query-log
sentinel absence. Do not dump raw app logs on failure; report sanitized status.
Use trap cleanup for containers/networks on success, failure or interruption.

Exercise actual MCP initialization and tools/list with the exact local
Host header, not only a 401. The existing integration fixture constructs a
synthetic Base64 AAD principal with appid, oid and `roles: AskHuman.Invoke`;
that is suitable only inside this isolated local test, never at public ingress.
The neighboring MCP test uses protocolVersion 2025-06-18, initialized
notification and an mcp-session-id. Reuse those semantics and assert valid
JSON-RPC results and the expected tool registration, not just HTTP 200.
Do not send tools/call, an authenticated human request or any real callback.

The parent image regression overlaps startup coverage; coordinate rather than
adding another broad Python test. It still needs the new callback placeholder
and MCP coverage regardless of where the CI smoke is implemented.

## Executed Checks and Limitations

* `bash -n scripts/deploy_azure.sh` passed; script commands were not invoked.
* `docker compose --env-file /dev/null config --quiet` passed; .env was not read.
* `command -v docker bicep az node jq shellcheck` found Docker, Node and jq;
  Bicep, Azure CLI and ShellCheck were not on PATH. No tools were installed.
* Public registry manifest checks verified the exact Python base digest.
* Public Microsoft documentation was fetched without tenant credentials.
* Research-document editor diagnostics passed after initial creation.
* No product files were changed, no shell regression or application test was
  run, and no image build/start, Azure deployment, registry publish or call was
  performed in this research session. No product fix is claimed as verified.

## Recommended Next Checks

* [ ] Implementation-capable parent: apply remaining product corrections and
  immediately run the narrow stub regression after the first substantive edit.
* [ ] Run scoped formatting, lint, typing and deploy stub tests using the
  existing approved Python environment; run shell syntax on both scripts.
* [ ] Compile all Bicep modules/root and parameters with dummy values and the
  new callback URL; regenerate infra/main.json only using a genuine compiler.
* [ ] Load the locally built image and run bounded migration/health/MCP smoke.
* [ ] External owner: verify exact ACS role and effective App table retention,
  purge semantics, image pull and target revision/auth boundaries.
* [ ] Release owner: record DR approvals and bound what-if/release acceptance;
  authorize live evidence separately. No paid test is authorized by this work.

## References

* .copilot-tracking/reviews/rpi/2026-09-16/ask-my-human-tight-mvp-plan-002-validation.md
* .copilot-tracking/reviews/rpi/2026-09-16/ask-my-human-tight-mvp-plan-004-validation.md
* scripts/deploy_azure.sh
* infra/main.bicep
* infra/modules/container-app.bicep
* infra/modules/communications-acs-role-assignment.bicep
* infra/modules/observability.bicep
* infra/environments/dev.bicepparam
* .github/workflows/ci.yml
* Dockerfile
* compose.yaml
* .dockerignore
* tests/integration/test_asgi_app.py
* src/ask_my_human/main.py
* src/ask_my_human/security/agent.py
* .copilot-tracking/details/2026-09-15/ask-my-human-tight-mvp-details.md
* [Webhook authentication](https://learn.microsoft.com/en-us/azure/communication-services/how-tos/call-automation/secure-webhook-endpoint)
* [ACS authentication](https://learn.microsoft.com/en-us/azure/communication-services/concepts/authentication)
* [Built-in role index](https://learn.microsoft.com/en-us/azure/role-based-access-control/built-in-roles)
* [Retention behavior](https://learn.microsoft.com/en-us/azure/azure-monitor/logs/data-retention-configure)
* [Workspace schema](https://learn.microsoft.com/en-us/azure/templates/microsoft.operationalinsights/2023-09-01/workspaces)
* [Table schema](https://learn.microsoft.com/en-us/azure/templates/microsoft.operationalinsights/2023-09-01/workspaces/tables)
* [Public Python registry manifest](https://registry-1.docker.io/v2/library/python/manifests/3.12-slim-bookworm)

## Clarifying Questions

* An implementation-capable parent must apply product changes; the active mode
  cannot fulfill the user's implementation request.
* No additional product-design clarification is required. External owners must
  supply the exact role definition and approve release/retention policy gates.