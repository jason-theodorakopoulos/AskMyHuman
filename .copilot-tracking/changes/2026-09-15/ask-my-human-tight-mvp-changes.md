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
