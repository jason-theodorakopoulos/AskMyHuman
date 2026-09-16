<!-- markdownlint-disable-file -->
# Changes Log: AskMyHuman Tight MVP

## Metadata

* Date: 2026-09-15
* Related plan: `.copilot-tracking/plans/2026-09-15/ask-my-human-tight-mvp-plan.instructions.md`
* Implementation commit: `9322aa6` (merge of Phase 0 implementation)
* Scope implemented: Implementation Phases 0, 1A, and 1B

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

## Phase 2 Changes

### Step 2.1: ASGI Composition

* Added `src/ask_my_human/main.py` as the sole ASGI composition root that builds settings, telemetry, the ACS client, the PostgreSQL pool, the repository, the application service, the maintenance loops, the HTTP routers, and the MCP application in one process.
* Added lifespan-owned resources with late-bound use-case, callback-validator, and pool slots so routers that are constructed before startup fail closed instead of importing runtime state.
* Added a `RuntimeFactory` seam with `create_azure_runtime` as the default so the composed application is testable with fakes.
* Added `tests/integration/test_asgi_app.py` and `tests/unit/test_main.py`.

## Phase 5 Changes

### Step 5.1 And Step 5.2: Deployment Automation

* Added `scripts/deploy_azure.sh` with `what-if`, `deploy`, and `verify` subcommands.
* `deploy` builds an image tagged with the full Git commit SHA, deploys the resource-group Bicep template, verifies that the ready revision runs that exact image and is active, running, and healthy, and then asserts that `/v1/requests`, `/mcp`, and the ACS callback all reject unauthenticated callers.

### Step 5.3: Live Validation Matrix

* Extended `tests/e2e/test_live_call.py` with unauthenticated-request rejection, invalid callback-token rejection, unanswered-call expiry, client-cancellation exactly-once termination, and one-call-one-terminal-row idempotency scenarios.
* All live scenarios remain gated behind the `live` marker and `RUN_LIVE_AZURE_TESTS=1`.

### Deployment Defects Found And Fixed While Running The Container

* Fixed allow-list environment parsing. `AUTHORIZED_AGENT_APP_IDS` and `MCP_ALLOWED_HOSTS` were JSON-decoded by pydantic-settings before validation, so the documented comma-separated deployment values raised a settings error. Both fields now use `NoDecode`.
* Added the `aiohttp` dependency. `DefaultAzureCredential` and the async `CallAutomationClient` require an async transport that the image did not contain.
* Fixed database migrations in the container. `migrations/env.py` now falls back to `DATABASE_URL` and normalizes the driver, and `alembic.ini` no longer hardcodes a localhost URL, so container startup no longer fails in `alembic upgrade head`.
* Fixed the MCP transport-security host check. The MCP server compares the full `Host` header including the port, so each allowed host is now expanded to both `host` and `host:*` with matching origins.

## Phase 5 Validation

* Generated schema drift check passed.
* Ruff formatting and lint passed for 76 Python files.
* Non-live suite passed with 174 tests at 92.21% coverage against the 90% gate.
* `docker compose config` passed, the image built, and the running container served health probes, OAuth protected-resource metadata, authenticated-only `/v1/requests`, token-checked ACS callbacks, and a full MCP initialize and tools-list exchange.
* Every Bicep template and every environment parameter file compiled.
* Steps 5.1, 5.2, and 5.3 were not executed. They require a real subscription, registry, ACS number, and Entra registrations that are unavailable in this environment, and Step 5.3 places billable phone calls.

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

Phase 1A delivers all independently testable application implementations for persistence, orchestration, telephony, security, HTTP, health, OAuth metadata, MCP, and observability. Phase 1B delivers all independently compilable public-endpoint Azure infrastructure modules. Phase 2 composition is now implemented, the composed container has been verified end to end locally, and Phase 5 supplies repeatable deployment and live-validation automation. Phase 5 execution remains blocked on tenant-owned Azure inputs.
