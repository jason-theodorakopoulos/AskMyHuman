---
title: AskMyHuman Tight MVP Changes Log
description: Implementation history, review corrections, and outstanding release evidence for the tight MVP.
---

## Metadata

* Date: 2026-09-15
* Related plan: `.copilot-tracking/plans/2026-09-15/ask-my-human-tight-mvp-plan.instructions.md`
* Implementation commit: `9322aa6` (merge of Phase 0 implementation)
* Historical scope: Implementation Phases 0, 1A, and 1B; current integration and release implementation is inventoried below.

## Phase 0 Changes

### Step 0.1: Python Package And Dependency Baseline

* Added Python 3.12 project metadata in `.python-version` and `pyproject.toml`.
* Added the uv dependency lock in `uv.lock`.
* Added the `src/ask_my_human` package and planned package markers.

### Step 0.2: Configuration And Public Contracts

* Added typed environment settings in `src/ask_my_human/config.py`.
* Added request, terminal result, and execution-error contracts in `src/ask_my_human/contracts.py` and `src/ask_my_human/errors.py`.
* Added deterministic schema export in `scripts/export_schemas.py` and three checked-in schemas under `schemas/`.
* Added `.env.example` plus contract and configuration tests.

### Step 0.3: Domain State And Application Ports

* Added internal request, principal, and callback event models.
* Added pending-to-terminal transition logic.
* Added inbound use-case, repository, telephony, clock, and telemetry protocols.
* Added deterministic use-case and clock fakes plus transition tests.

### Step 0.4: Infrastructure Module Contracts

* Added the resource-group Bicep contract in `infra/main.bicep`.
* Added environment-variable bindings in `infra/environments/dev.bicepparam`.

### Step 0.5: Foundation Validation

* Added pytest, Ruff, mypy, coverage, and live-test marker configuration.
* Added focused contract, configuration, error, and transition tests.
* Validation results are recorded in the Phase 0 review log.

## Changed Files

The Phase 0 merge added 31 files across project configuration, schemas, scripts,
source contracts, tests, and Bicep interface definitions. The authoritative file
list is the `9322aa6` commit stat.

## Review Corrections

Phase 0 review corrected the following foundation defects:

* Added schema-level terminal result discriminators and negative contract tests.
* Aligned raw request prompt length and nonblank validation across Pydantic and JSON Schema.
* Made phone-number settings secret-valued, hid invalid settings inputs from validation errors, and secured phone parameters in Bicep.
* Added explicit cancellation to the inbound use-case protocol.
* Restricted telemetry fields to frozen enums and low-cardinality values.
* Added deterministic repository, call gateway, cancellation, clock, use-case, and telemetry fakes with behavioral tests.
* Froze all six Phase 1B Bicep module input and output contracts.
* Reconciled infrastructure research to reference an existing numbered ACS resource.

Final local validation:

* Lock validation and frozen dependency synchronization passed.
* Generated schema drift check passed.
* Focused Phase 0 suite passed with 47 tests.
* Strict mypy passed for eight source and test-support files.
* Ruff formatting and lint checks passed.
* `git diff --check` passed.

Publication status:

* Review corrections remain uncommitted because no commit was requested.
* Step 0.5 remains open for commit publication, clean-checkout reproduction, Bicep compilation when tooling is available, and workstream-owner hash distribution.

## Phase 1A Changes

### Step 1A.1: PostgreSQL Persistence

* Added Alembic configuration and the initial `human_requests` migration.
* Added async Psycopg pool lifecycle and atomic PostgreSQL repository semantics.
* Added PostgreSQL 16 integration coverage for migrations, admission, idempotency, terminal races, restart durability, expiry, and purge.

### Step 1A.2: Core Orchestration And Maintenance

* Added synchronous request orchestration with fixed cutoffs, polling, creator-aware cancellation, first-terminal arbitration, and best-effort hang-up.
* Added in-process stale-expiry and terminal-purge loops.
* Persisted sanitized technical errors so stable error replay survives service, repository, and pool replacement.

### Step 1A.3: ACS Telephony

* Added the async ACS Call Automation gateway for one outbound call and one choice or speech recognition action.
* Added strict callback parsing, numeric result-code mapping, acknowledgement, and hang-up behavior.
* Added six sanitized ACS fixtures and focused telephony tests.

### Step 1A.4: Security

* Added trusted Container Apps principal parsing with role and authorized-client enforcement.
* Added bounded OpenID and JWKS caching for ACS callback JWT validation, including key refresh.

### Step 1A.5: HTTP Adapters

* Added injectable FastAPI routers for synchronous requests and ACS callbacks.
* Added stable error mapping, disconnect cancellation, JWT-first callback validation, and duplicate callback acknowledgement.

### Step 1A.6: Platform API

* Added liveness and readiness routes with sanitized responses and side-effect-free pool checks.
* Added Entra OAuth protected-resource metadata.

### Step 1A.7: MCP Adapter

* Added one Streamable HTTP `ask_human` tool using the frozen schemas and direct use-case dispatch.
* Added structured success and execution-error results, principal mapping, and cancellation propagation.

### Step 1A.8: Observability

* Added content-free Azure Monitor OpenTelemetry spans, metrics, pending gauge, and ASGI instrumentation.
* Added sensitive-sentinel tests for prompts, answers, phone numbers, keys, tokens, and callback bodies.

## Phase 1B Changes

### Step 1B.1: Public PostgreSQL

* Added PostgreSQL Flexible Server 16 with public network access and an Azure-services firewall rule.
* Enforced TLS with secure administrator inputs and removed the VNet, delegated subnets, and private DNS module.

### Step 1B.2: Identity And Communications

* Added user-assigned identity and existing ACS reference modules.
* Added Azure AI multi-service resources and least-privilege role assignments.
* Added a nested ACS-scoped role-assignment support module for cross-resource-group deployments.

### Step 1B.3: Observability Infrastructure

* Added Log Analytics and workspace-based Application Insights with explicit 30-day retention and public ingestion and query access.

### Step 1B.4: Container App

* Added a public Container Apps environment and one externally accessible app with one replica.
* Added managed identity, ACR pull, secret references, health probes, Entra authentication, and the sole ACS callback exclusion.
* Added a nested ACR-scoped role-assignment support module for cross-resource-group deployments.

## Phase 1 Validation

* `uv lock --check` passed.
* Generated schema drift check passed.
* Combined unit, contract, and PostgreSQL integration suite passed with 150 tests.
* Strict mypy passed for 28 source files.
* Ruff formatting and lint checks passed for 54 Python files.
* All seven Phase 1B Bicep and support modules compiled with Bicep CLI 0.47.16 with zero warnings and zero errors.
* Workspace diagnostics and `git diff --check` passed.

## Additional Or Deviating Changes

* Extended internal domain and repository contracts for durable technical-error replay after process replacement.
  * Public request, result, and execution-error wire schemas remain unchanged.
* Added two nested role-assignment support modules.
  * Bicep requires a nested deployment when assigning roles to existing ACS and ACR resources in another resource group or subscription.
* Replaced private VNet integration with public service endpoints for the tight MVP.
  * Removed `infra/modules/network.bicep`, subnet inputs, and private DNS inputs.
  * PostgreSQL permits Azure-hosted clients through the documented `0.0.0.0` Azure-services rule, not an unrestricted internet address range.
  * Entra authentication, ACS callback JWT validation, managed identity, TLS, secure parameters, and one-replica scaling remain unchanged.

## Release Summary

Phase 1A delivers all independently testable application implementations for persistence, orchestration, telephony, security, HTTP, health, OAuth metadata, MCP, and observability. Phase 1B delivers all independently compilable public-endpoint Azure infrastructure modules. This historical summary predates the integration and release files now present; their existence does not establish passing release gates.

## Phase 5 Resumption: 2026-09-16

* User authorized Phase 5 implementation, prerequisite corrections, and Azure CLI authentication using the ignored local environment file, with low-cost Azure tiers where compatible.
* Existing Phase 2 composition, Phase 3 image/CI/live harness, Phase 4 documentation, and Phase 5 deployment helper require validation and reconciliation with the 2026-09-16 review findings.
* No deployment, what-if review, paid call, retention-policy approval, or target-client acceptance is claimed at resumption.
* Phase 5.1 starts with Azure inventory and external-input verification; prerequisite validation can proceed independently without Azure mutations or paid calls.

## Review Inventory: 2026-09-16

The metadata and validation results above preserve the historical record. The
following inventory supplements that history without restoring removed success
claims or marking whole phases complete. Review repairs are ongoing; final
checks will be recorded in the review log against the final repository state.

### Phase 2 Integration Present

* `src/ask_my_human/main.py` contains ASGI composition, dependency lifecycle,
  maintenance tasks, HTTP routes, and mounted MCP transport.
* `tests/integration/test_asgi_app.py` provides composition coverage using
  fakes and spies plus a real application-container migration/startup smoke.
* `infra/main.bicep` and `infra/environments/dev.bicepparam` compose the Azure
  modules and environment bindings. Their presence is not deployed evidence.
* Integration support includes comma-separated settings decoding, async Azure
  transport dependencies, optional telemetry bootstrap, and environment-driven
  migrations. Current correctness and final checks remain with their owners.

### Phase 3 Release Code Present

* `Dockerfile` provides the application image and migration-before-server
  startup path; `compose.yaml` provides PostgreSQL and placeholder app startup
  configuration with loopback-only published ports.
* `.github/workflows/ci.yml` defines local checks and image build validation.
  Building the image does not demonstrate its startup, migration, and health
  behavior; a bounded non-live container smoke result remains required.
* `tests/e2e/test_live_call.py` provides an opt-in live harness. A test module's
  presence, collection, or default skip does not establish live acceptance.

### Phase 4 Documentation And Validation Partial

* Corrected `README.md` to describe `expired/deadline_exceeded` as an HTTP 200
  terminal result and successful MCP result, with no unconditional delivery
  promise after cancellation or connection loss.
* Distinguished subject-scoped pending joins and terminal replay from changed
  payload conflict, distinct-request 429 admission, and unsupported asynchronous
  resume. Joining does not create another call or reset the deadline.
* Added Markdown frontmatter, valid JSON and text fences, navigable README
  planning references, and required punctuation/style corrections.
* Separated host settings from literal placeholder Compose configuration,
  identified the telemetry environment-read exception, and documented the
  supported 210/205-second timing policy as configurable defaults.
* Documented the required split between `ACS_CALLBACK_URL` (public HTTPS full
  `/v1/callbacks/acs` endpoint) and `ACS_CALLBACK_AUDIENCE` (immutable ACS
  resource ID string). Source and deployment binding repairs remain with the
  implementation owners; this entry does not assert their validation passed.
* Documented the post-edit complete local gate plus editor diagnostics and
  `git diff --check` Markdown fallback without adding a Markdown toolchain.
* The user approved DD-06 on 2026-09-16: Step 4.2 command evidence covers local
  validation; deployment and paid live acceptance remain mandatory in Phases 5
  and 6. The plan, detailed criterion, and README now reflect that decision.

### Phase 5 Deployment And Live Gates Partial

* `scripts/deploy_azure.sh` exists as deployment assistance, not proof that the
  whole release flow ran. Its reviewed action syntax and required inputs must
  be inspected after concurrent repairs; default help, explicit approvals,
  immutable digest/revision checks, and authenticated health checks are under
  review. No automatic paid calls are authorized.
* README operator requirements now include `AskHuman.Invoke`, authorized
  client IDs, target MCP timeout of at least 225 seconds and cancellation,
  retention approval, reviewed what-if, exact image/revision evidence, and
  authenticated readiness/liveness and rejection checks.
* Added last-known-good rollback guidance and first-deployment blocker handling
  with sanitized diagnostics, bounded resource retention, and approved cleanup.
* The live harness requires outcome-specific evidence and remaining scenario
  coverage. HTTP tests and one database row cannot substitute for live MCP
  behavior or provider-side one-call evidence. Review assertion repairs do not
  establish that live scenarios ran.
* Required evidence includes every availability/decision outcome, join/replay,
  duplicate callbacks, MCP timing/cancellation, all sensitive telemetry sentinel
  categories with bounded ingestion, and production-path retention purge.
  Approved carrier limitations must be explicit; skipped queries are not passes.
* Tenant inputs, operator approvals, deployment, and paid live evidence remain
  external gates. No secret reads, Azure mutations, or paid calls were performed
  by this documentation repair.

### Phase 6 Final Handoff Pending

* The complete final-state local gate and live-evidence review remain required
  after all owner repairs; historical passes are not final-state results.
* Final checks, unresolved blockers, owners, and next actions will be recorded
  in the review log. No final pass or release-ready status is claimed here.

### Review Evidence And Open Decisions

* Finalized findings: `.copilot-tracking/reviews/rpi/2026-09-16/ask-my-human-tight-mvp-plan-005-validation.md`
* Required gates: `.copilot-tracking/details/2026-09-15/ask-my-human-tight-mvp-details.md`, Steps 4.1 through 6.3
* Contract evidence: `.copilot-tracking/research/2026-09-15/tight-mvp-scope-research.md`, State, Deadline, and Idempotency
* Operator decision resolved: DD-06 explicitly reconciles Step 4.2 command
  evidence with Phase 5 prerequisites without waiving any release gate.

## Final Local Review Corrections: 2026-09-16

This section supersedes the earlier in-progress inventory statements, not the
historical implementation results or user-owned release-resumption record.

* Corrected deadline/cancellation bounds, late callback cleanup, first-terminal
  acknowledgement ownership, correlated connected-only recognition, technical
  callback failures, and database expiry predicates.
* Added additive migration `20260916_0002_recognition_guard.py` for durable
  once-only recognition; apply it before using the updated repository.
* Unified HTTP/MCP authorization, separated callback endpoint and immutable
  audience settings, bounded discovery, and removed sensitive exception/access
  logging while instrumenting actual operations and pending state.
* Repaired maintenance recovery, stale-call cleanup, startup cancellation,
  task drainage, readiness, and acknowledgement completion handling.
* Added explicit Application Insights table retention, pinned image digest,
  loopback Compose bindings, approval-bound immutable deployments, authenticated
  bounded health checks, rollback safeguards, and a no-call CI image smoke.
* Expanded the fail-closed live harness, mandatory telemetry evidence and
  independent provider attestations; verified the actual HTTP and deployment
  evidence contracts with offline regressions. No live acceptance was executed.
* Corrected documentation and environment examples while preserving preexisting
  user changes. No commit, publication, deployment, or paid call was performed
  by this review continuation.
* Final pre-documentation-closeout gate: 429 non-live tests passed with 91.28%
  branch-inclusive coverage; 20 live tests skipped without opt-in. Formatting,
  Ruff, strict mypy, lock/frozen sync, schema drift, Compose, image runtime smoke,
  shell checks, and all Bicep templates/parameters passed. The final review log
  records the required post-documentation rerun and any remaining external gates.

## Phase 5 Deployment Execution: 2026-09-16

Steps 5.1 and 5.2 completed against subscription `ME-MngEnvMCAP721432-dkalamaras-1`,
resource group `rg-askmyhuman`, region `swedencentral`. Step 5.3 remains open.

### Modified

* infra/modules/communications-acs-role-assignment.bicep - Names the assignment from
  the identity resource id and uses the existing Communication and Email Service Owner
  role definition.
* infra/modules/communications.bicep - Threads the container identity resource id
  through to the ACS role assignment.
* infra/modules/container-app-acr-role-assignment.bicep - Names the AcrPull assignment
  from the principal resource id.
* infra/modules/container-app.bicep - Passes the identity resource id to the registry
  pull role assignment.
* infra/main.bicep - Supplies the container identity resource id to the communications
  module.
* Dockerfile - Builds without BuildKit-only mount options so classic ACR Tasks succeed.
* scripts/deploy_azure.sh - Adds bounded per-command Azure timeouts, scopes what-if
  property paths to property changes, accepts resource names containing spaces and
  parentheses, and treats a running-at-max-scale revision as ready.
* src/ask_my_human/application/service.py - Hangs up orphaned calls and skips the
  redundant hang-up once a request is responded.
* tests/e2e/test_live_call.py - Binds deployment evidence to source sha, image digest,
  revision suffix, authentication proof, and the observed running state.
* tests/unit/test_deploy_script.py - Covers container probe paths in the what-if fixture.
* .env.example - Documents the immutable ACS audience and the callback URL.

## Additional or Deviating Changes

* Substituted the Communication and Email Service Owner role for the originally planned
  ACS data role.
  * Reason: The planned role definition does not exist; ACS exposes no dataActions model,
    and this is the only ACS role available in the tenant.
* Removed BuildKit cache and bind mounts from the image build.
  * Reason: ACR Tasks uses the classic builder, which rejects the `--mount` option.
* Derived role assignment names from identity resource ids rather than principal ids.
  * Reason: Principal ids are unknown before deployment, so what-if reported the
    assignments as Unsupported and the strict review filter rejected the change set.
* Relaxed the deploy script verification gate to accept `RunningAtMaxScale`.
  * Reason: With a single fixed replica, Container Apps never reports plain `Running`.

## Phase 5A Local Start: 2026-09-16

* Fetched origin and fast-forwarded local main by 12 commits to `ff4dc43`.
  Created `feature/bojan-phase5-live-validation` from that updated main.
* Started Step 5A.1 with `infra/modules/communications-acs-diagnostics.bicep`.
  It targets the existing ACS resource and sends `CallAutomationOperational`
  and `CallSummary` to resource-specific Log Analytics tables. It does not
  enable all log categories, metrics, or application auto-instrumentation.
* Wired the existing observability workspace output through the communications
  module. The diagnostics child deployment uses the ACS subscription and
  resource group, matching the existing role-assignment module's scope.
  No new root parameter, public output, or development parameter binding was added.
* Local validation passed: `az bicep build --file infra/main.bicep --stdout --only-show-errors`;
  structured compiled-template checks verified workspace binding, cross-resource-group
  scope, one diagnostic setting, the two enabled categories, and the dedicated
  destination. Editor diagnostics reported no errors in the three Bicep files.
* Deployment-script review found no resource-type allowlist that needs changing.
  Its Bash regression suite was not run: the local Windows environment has no
  pytest, and the available WSL Ubuntu environment has neither pytest nor jq.
* Step 5A.1 remains incomplete. Before applying, verify the target resource's
  category identifiers and content fields; the configured category is
  `CallAutomationOperational`, not the planning label `CallAutomationOperationalLogs`.
  Enable optional `CallDiagnostics` only after confirming support. Reviewed what-if,
  deployment approval, and actual provider-log ingestion evidence are still required.
* No Azure resource changes, paid calls, commits, or branch publication were performed.
  Existing local environment files and ignored meeting notes were preserved.

## Phase 5A Evidence Feasibility Check: 2026-09-16

* The current Azure CLI account cache has no subscription named
  `ME-MngEnvMCAP721432-dkalamaras-1`, the deployment target recorded above.
  No target deployment identifiers were available from the allowlisted local
  environment-file fields. Target-specific category discovery and reviewed what-if
  cannot proceed in this session until authorized access is available. Do not
  substitute the older `acsrgj1rg` discovery target.
* Step 5A.2 has an evidence-source blocker, not just a missing script.
  The [ACS incoming-operations schema](https://learn.microsoft.com/en-us/azure/azure-monitor/reference/tables/acscallautomationincomingoperations)
  documents provider call identifiers, but not the application's request ID or
  `operation_context`. The gateway sends the request ID as `operation_context`;
  its appearance in provider logs has not been demonstrated. Do not equate a
  provider `OperationId` or `CorrelationId` with the application request ID.
* The current content-free telemetry allowlist does not include `call_id`,
  `event_id`, or `delivery_id`. Provider call summaries do not establish which
  callback deliveries the application accepted or when a replay joined an
  existing pending request. Those facts are required by `_Delivery` and
  `_PendingJoin` in [the live harness](../../../tests/e2e/test_live_call.py).
* A maximum ingestion timestamp is not the required `complete_through` proof.
  Microsoft documents [ingestion_time()](https://learn.microsoft.com/en-us/kusto/query/ingestion-time-function?view=azure-monitor)
  as approximate and unsuitable for ordering concurrent ingestion operations.
  Neither the query time, the latest ingested row, nor a fixed delay establishes
  that all provider or telemetry records through the test interval have arrived.
* Before implementing a harness-valid harvester, the release owner must approve
  an evidence contract covering provider-to-request correlation, content-free
  accepted-delivery and pending-join observations, and a defensible export
  completion mechanism. Keep source provenance explicit. Preserve independent
  provider attempt evidence and keep partial exports fail-closed; do not infer
  missing identities from application database rows or silently accept partial data.
* Steps 5A.1 through 5A.4 and the paid live matrix remain incomplete. No Azure
  mutation, credential retrieval, paid call, or change to the harness gates was made.

## Phase 5A Offline Evidence Implementation: 2026-09-16

### Approval And Scope

* The user approved revising the evidence contract and continuing offline after
  the feasibility findings above. They asked to be notified before push/PR work;
  the branch remains unpublished, with no commit or PR created.
* The revised contract separates independent provider CreateCall API-result rows
  from application call correlations, accepted callback receipts, and pending
  joins. It does not infer provider identities from database rows or treat media
  `OperationId` as an application request ID.
* A hash-bound operator review of a bounded snapshot replaces the unsupported
  `complete_through` design. Diagnostic/sampling/ingestion checks and explicit
  acceptance of residual late-arrival risk are required; none proves global
  ingestion completeness. This approved revision resolves the offline design
  blocker, not target Azure access, actual ingestion, or release acceptance.

### Implemented

* Added `src/ask_my_human/live_evidence.py` with strict resource/revision/workspace
  scope, provider/application reconciliation, time-window validation, and a
  separate reviewer-bound SHA-256 review of the exact export bytes.
* Added the read-only `scripts/harvest_live_evidence.py`. It requires full query
  responses and exact projected columns, rejects sampled/oversized/unreconciled
  data, retains repeated provider rows, and never creates a review, reads the
  application database, places calls, or overwrites an existing export.
* Added explicit call-created, pending-join, and accepted-callback observations.
  Opaque provider call/event IDs are hashed before application export. Receipt
  IDs identify individual HTTP deliveries after the authenticated batch finishes;
  they do not prove ACS received the response or a callback mutated stored state.
* Bound application telemetry to `CONTAINER_APP_REVISION` and requested full
  sampling. Automatic HTTP/SDK/body instrumentation remains disabled. Operators
  must still verify sampler overrides and ingestion settings on the deployment.
* Migrated the live harness to reviewed snapshots while preserving provider-row
  counts, exact terminal results, duplicate receipts, pending joins, privacy
  sentinels, and all deployment/database/scenario/paid-call gates. Export refreshes
  tolerate transient file-pair mismatches but never accept a bad hash or a window
  missing the scenario start.
* Updated the README and Phase 5A details with provenance, fail-closed limits,
  immutable archives, active-pair refresh, a deliberately non-passing review
  template, and the separate external gates. No database schema, public JSON
  contract, deployment framework, retry path, or service topology changed.

### Local Verification

* `uv lock --check --offline` passed; project metadata and the unchanged lock agree.
  This is not evidence of a successful frozen environment installation.
* Pinned Ruff `0.16.7` passed repository-wide format and lint checks. Because the
  mirror lacked this version and the Python wheel host failed TLS, the official
  GitHub release archive was downloaded and its published SHA-256 verified before
  execution. Dependency manifests and lockfile were not altered.
* `python -m mypy src scripts/harvest_live_evidence.py` passed for all 31 production
  files. Explicit checking of all 18 changed Python files with
  `--follow-imports=silent` also passed. Neither is the full `mypy src tests` gate.
* The Windows-available unit and contract run passed 396 tests, with 23 Unix
  verifier cases deselected and the Bash deployment-script module excluded.
  Branch-aware coverage was 96.34% across the evidence contract, harvester,
  callback observations, and telemetry module. This is scoped coverage, not the
  required full-suite coverage result.
* Public schema export drift checking passed with `PYTHONPATH=src`. With
  `RUN_LIVE_AZURE_TESTS=0`, all 20 live scenarios skipped. Focused refresh/privacy
  regressions passed, including temporary invalid pairs and missing window starts.
* All 9 Bicep templates and the development parameter file compiled using only
  synthetic CI placeholders, with stdout output and no generated-file changes.
  This compilation does not establish target category support or ingestion.

### Remaining Gates

* Local runner/package access: frozen sync still fails at the public wheel host;
  the configured mirror lacks pinned releases including Alembic `1.20.0` and
  PyJWT `2.14.0`. The Windows HTTPS fallback also failed, so no downloaded path
  from that failed command was treated as a package. The selected Python 3.12
  environment is only partially lock-aligned. Full `mypy src tests` reports
  missing Alembic/SQLAlchemy/testcontainers imports and JSON Schema stubs, not
  changed-source typing failures. Owner: validation runner operator. Next action:
  run the unchanged frozen environment gate on a runner with package access.
* Linux/Docker validation: Bash/jq verifier fixtures, full non-live coverage,
  PostgreSQL integration, Compose/image build, and container smoke remain unrun
  here. Owner: validation runner operator. Next action: execute the existing CI
  gates on a Linux/Docker-capable runner after publication is authorized.
* Azure/release validation: target subscription access is still unavailable.
  ACS category/schema/content review, reviewed what-if and deployment, live
  ingestion/sampling checks, isolated database, carrier arrangements, and all
  paid scenarios remain separately blocked. Owner: target deployment/release
  operator. No older discovery target may be substituted.
* Do not mark Phase 5A or Step 5.3 complete, claim a merge-ready gate, or treat
  documentation and offline tests as Azure or live acceptance. No Azure resource
  mutation, paid call, commit, push, or PR was performed in this work.

## Phase 5A Azure Verification: 2026-09-17

### Verified

* The deployed revision `askmyhuman--b5a16f2ff092-6ab2ba862308` is active,
  healthy, and running one replica at 100 percent traffic.
* The isolated `askmyhuman_live` database is active at migration
  `20260916_0002` and contains one `responded/approved` row and one
  `expired/no_answer` row.
* Independent provider evidence contains two successful `CreateCall` results.
  Both provider call identifiers reconcile to content-free application call
  correlations from the same revision.
* The read-only harvester emitted a strict two-call snapshot with two provider
  attempts, two correlations, six callback receipts, and zero pending joins.
  The snapshot SHA-256 is
  `ea89a0f68bcdc2770a0cf9afa692b148bfcbb3cf72306992ffe37f761d362795`.
* Exact replay of request `81bb922c-bc0c-4f60-9fd5-99d5f272dee7` returned the
  original `responded/approved` result without creating a second row.

### Modified

* infra/modules/communications-acs-diagnostics.bicep - Enables the
  target-supported `CallDiagnostics` category for carrier and media evidence.

### Validation

* Evidence and live-harness focused suite passed with 206 tests.
* The full Bicep composition compiled with all three ACS diagnostic categories.
* Application Insights is workspace-based with 30-day retention, no configured
  ingestion sampling percentage, and `ItemCount=1` on evidence observations.
* `git diff --check` and editor diagnostics passed.

### Remaining Gates

* The exported snapshot has no authorized exact-byte review and does not claim
  global ingestion completeness. Bounded late-arrival risk remains.
* `ACSCallSummary` had no rows at verification time. `CallDiagnostics` is live,
  but its dedicated-table ingestion requires a subsequent applicable call.
* Silence, rejection, free-form answer, busy, decline, mid-call disconnect,
  forced deadline, and initiating-client cancellation remain untested.
* Request `4745f499-fdcd-443a-b2ff-c80abe4c5dc6` proves natural no-answer only.
  Its observer failed before cancellation, so it is not cancellation evidence.

### Diagnostics Deployment

* Source SHA: `088688825d4d5b6a1f4b819a986d1877ea5e7f3b`
* Image digest:
  `sha256:ef92ee186965634336358bd760bf45ac8a2976aad9bb16d89967341d999b40bb`
* Revision: `askmyhuman--088688825d4d-ef92ee186965`
* State: active, healthy, `RunningAtMaxScale`, one replica, and 100 percent traffic
* Authentication: deployment verifier passed authenticated and anonymous-boundary checks
* Diagnostic setting: `askmyhuman-call-evidence` routes the three enabled call
  categories to workspace `60b8ef6d-ef0c-4615-83fd-ac836250baac`

## Phase 6 Final Validation: 2026-09-17

### Complete Repository Gate

* Lock validation, frozen synchronization, schema drift, Ruff format and lint,
  strict mypy, Compose configuration, shell syntax, Docker build and runtime
  smoke, and all Bicep builds passed.
* The non-live suite passed with 521 tests and 92.09 percent branch-inclusive
  coverage. Twenty live tests were deselected and are not counted as acceptance.
* The image smoke verified migrations, health, authentication rejection, MCP
  initialization, an empty request table, and log privacy without placing a call.
* The final source revision remains active and healthy with one replica, the
  expected immutable digest, and 100 percent traffic.

### Release Status

The release remains blocked on Step 6.2. The reviewed live matrix does not yet
establish rejection, free-form answer, silence, busy, decline, disconnect,
forced deadline, HTTP cancellation, or MCP deadline behavior. No local code
defect was found during final validation.

### Live Cancellation Finding

Two controlled requests tested initiating-client cancellation against the live
Container App. Cancelling an active `httpx` request on a shared client produced
request `dea0f688-14e0-4679-a9b6-95a592b8902e`, which terminated as a sanitized
`dependency_failure` after 38 seconds. Repeating the test with a dedicated
`Connection: close` transport produced request
`f18f3f39-a9ff-45b5-be42-824fee83b6d8`, which terminated naturally as
`expired/no_answer`. In neither case did the application observe a disconnect
and persist `cancelled` within the required 15 seconds.

The dedicated-client harness experiment was reverted after the live check
disproved it. Local ASGI tests still validate direct disconnect signaling, but
the deployed ingress path does not provide equivalent evidence. Release requires
an explicit HTTP cancellation protocol or a formally approved HTTP limitation;
changing the public contract was not attempted.

### Additional Live Passes

* MCP Streamable HTTP cancellation passed on request
  `730b7272-1948-4572-a5ff-e3af5694f8e9`. The database persisted
  `expired/cancelled` 0.737 seconds after creation, and MCP replay returned the
  same request and terminal result without an execution error.
* The production `RequestMaintenance.purge_once()` path removed one controlled
  25-hour terminal row, retained the current terminal row, and cleaned up the
  probe data.
* Fourteen content-suppressed telemetry searches covered actual prompts,
  idempotency keys, phone, database credentials, ACS key, agent and deployment
  secrets, and authorization material. All returned zero matches.
* A strict latest-revision snapshot for the two HTTP cancellation attempts was
  exported with SHA-256
  `29cbdee76d1a33ae54d79946b9781e9bbbf9f3a6e236c9d78df1891d06ded94d`.
  It contains two provider attempts, two app correlations, six callback
  deliveries, and zero pending joins. It remains unreviewed.
* The MCP cancellation has one independent provider attempt, one app call
  correlation, two accepted callback deliveries, and a correlated database
  terminal result. Its strict snapshot SHA-256 is
  `fe3525ce9942d12efd847feef71bc75922f0543deff318a0c99866b4bf5502a4`.
  The snapshot remains unreviewed.

## Release Summary

The current Azure deployment is live and healthy with independent ACS provider
evidence, isolated live storage, strict evidence harvesting, three provider call
diagnostic categories, application JWT authentication, and passing local release
gates. Phase 5 and release acceptance remain partial until the reviewed live
matrix and retention evidence are complete or explicit carrier limitations are
approved.

## Phase 7 Start: 2026-09-17

The user requested that MCP invocations supply the human phone number instead of
using the fixed `MY_MOBILE_NUMBER` environment value. The implementation must
extend the durable request contract because callback-driven recognition reloads
request state after admission. No code, schema, migration, infrastructure, or
deployment change is claimed complete at this point.

## Phase 7 Local Implementation: 2026-09-17

### Added

* migrations/versions/20260917_0003_request_phone_number.py - Persists validated
  destinations, safely terminalizes legacy pending rows, and preserves terminal history.

### Modified

* The request contract and generated schema require E.164 `phoneNumber`.
* Persistence round-trips the destination and idempotency identity includes it.
* ACS call creation and recognition construct the target from each durable request.
* Runtime, Bicep, deployment, Compose, smoke, CI, and documentation surfaces no
  longer require `MY_MOBILE_NUMBER`.
* Contract, HTTP, MCP, service, persistence, migration, ACS, integration,
  deployment, and live-harness tests cover the caller-supplied destination.

### Validation

* Focused contract, MCP, ACS, migration, and persistence suites passed with 60 tests.
* The intended live destination validates against the exact request contract.
* No runtime or deployment reference to `MY_MOBILE_NUMBER` remains.
* The complete local release gate passed: lock and frozen sync, generated schema
  drift, Ruff formatting and lint, mypy over 58 source files, 538 non-live tests,
  92.03% coverage, Compose configuration, production image build, Bicep build,
  shell syntax, and whitespace validation.
