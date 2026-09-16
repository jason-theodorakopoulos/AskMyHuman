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

Phase 1A delivers all independently testable application implementations for persistence, orchestration, telephony, security, HTTP, health, OAuth metadata, MCP, and observability. Phase 1B delivers all independently compilable public-endpoint Azure infrastructure modules. Phase 2 composition remains intentionally unimplemented.

## Phase 2 Changes (Step 2.1 Completion)

Step 2.1, the sole ASGI application composition root, was found unimplemented
despite `Dockerfile`, `compose.yaml`, and CI already referencing
`ask_my_human.main:app`. This gap blocked the Phase 4 local merge gate and is
closed by this change.

* Added `src/ask_my_human/main.py` as the sole composition root: builds
  `Settings`, configures observability, opens the PostgreSQL pool and ACS
  client, constructs the service and maintenance loops, registers every HTTP
  router, and mounts the MCP Streamable HTTP app at `/` last, entering
  `mcp_server.session_manager.run()` around the host lifespan so the mounted
  sub-application's session manager runs under the parent app's lifespan.
* Added `tests/integration/test_asgi_app.py`, exercising the fully composed
  application through `fastapi.testclient.TestClient` against a real
  PostgreSQL testcontainer: liveness, readiness, OAuth metadata,
  unauthenticated-request rejection, missing-callback-token rejection, and
  that the MCP mount does not shadow HTTP routes.
* Added `aiohttp>=3.14.3,<4` to main dependencies. `azure-identity`'s async
  `DefaultAzureCredential` raises `ImportError: aiohttp package is not
  installed` at construction time without it; version pinned above the range
  flagged by the GitHub Advisory Database for a chunked-response parsing
  vulnerability.
* Added `types-jsonschema>=4.26,<5` to dev dependencies for mypy stubs.

### Isolated Defects Fixed During Composition And Gate Execution

These were pre-existing defects discovered while composing and validating the
application, not introduced by Step 2.1 itself. Each is isolated to its owning
module and does not change any frozen public contract:

* `src/ask_my_human/config.py` — `authorized_agent_app_ids` and
  `mcp_allowed_hosts` are `tuple[str, ...]` fields with a `split_csv` before
  validator, but `pydantic-settings`' `EnvSettingsSource` attempts JSON
  decoding of non-`str` field values before validators run, so any real
  environment-variable value (a bare UUID or hostname, as set in
  `compose.yaml` and `.env.example`) crashed `Settings()` with
  `SettingsError`. Annotated both fields with `pydantic_settings.NoDecode` so
  the raw string reaches `split_csv` unchanged.
* `src/ask_my_human/observability.py` — `configure_observability()`
  unconditionally called `configure_azure_monitor(...)`, which raises
  `ValueError: Instrumentation key cannot be none or empty` whenever no
  Application Insights connection string is available (the case for local
  Docker Compose and every test environment). `configure_observability` now
  resolves a connection string from the explicit argument or the
  `APPLICATIONINSIGHTS_CONNECTION_STRING` environment variable and skips
  exporter configuration entirely when neither is set, still returning an
  `AzureMonitorTelemetry` handle for content-free spans/metrics.
* `migrations/env.py` — Alembic's `env.py` never read `DATABASE_URL` and
  always connected using the hardcoded `alembic.ini` default
  (`postgresql+psycopg://localhost/ask_my_human`), so `alembic upgrade head`
  in the container entrypoint silently ignored the configured database and
  failed to connect in `docker compose up`. `env.py` now overrides
  `sqlalchemy.url` from `DATABASE_URL` when present, normalizing the
  `postgresql://` scheme to `postgresql+psycopg://` for SQLAlchemy's dialect
  loader.
* 36 pre-existing `mypy --strict` errors across eight unit/contract/integration
  test files (untyped generator fixtures, loosely typed `Settings(**dict)`
  construction, string literals used where enum members are required,
  `SpanExporter.export` parameter variance, and similar strict-mode-only
  issues) were corrected without changing any test's asserted behavior.

## Phase 4 Changes: Local Validation And Documentation

### Step 4.1: Pre-Documentation Local Merge Gate

All commands passed against the fixes above:

* `uv lock --check`, `uv sync --frozen --all-groups`
* `uv run python scripts/export_schemas.py --check`
* `uv run ruff format --check .`, `uv run ruff check .`
* `uv run mypy src tests` — 54 source files, zero errors
* `uv run pytest -m "not live" --cov=ask_my_human --cov-fail-under=90` — 156
  passed, 90.24% coverage
* `docker compose config --quiet`
* `docker build --tag ask-my-human:mvp .`
* `az bicep build --file infra/main.bicep`
* Manual smoke test: `docker compose up --build` brought up PostgreSQL and the
  application container; `alembic upgrade head` ran the migration against the
  compose network's `db` host, and `/health/live` and `/health/ready` both
  returned `200`.

### Step 4.2: Documentation

* Rewrote `README.md` with the verified one-turn behavior, request/result
  examples, architecture (including the DD-01 Play-and-Recognize-replaces-
  Voice-Live decision in the architecture section), local setup and
  validation commands, configuration reference, Azure prerequisites and
  deployment flow, the 210-second deadline, and explicit exclusions. No
  secret value or tenant-specific identifier is documented.
* `.gitignore` was not changed; no uncovered local artifact was produced by
  validation.

### Step 4.3: Post-Documentation Revalidation

The complete local merge gate (Step 4.1 command list) was rerun after the
README update and passed unchanged. No repository Markdown linter is
configured; `git diff --check` on `README.md` reported no whitespace errors.

## Updated Release Summary

Phases 0, 1A, 1B, 2, 3, and 4 are complete for the tight MVP. Phase 5 (Azure
deployment and live validation) remains gated on tenant-specific inputs
(existing ACS resource, Entra tenant/application registrations, target
subscription/region/registry, and retention approval) recorded as DR-01
through DR-05 in the planning log, and is not attempted by this change.
