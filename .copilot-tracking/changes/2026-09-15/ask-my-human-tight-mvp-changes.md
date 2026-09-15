<!-- markdownlint-disable-file -->
# Changes Log: AskMyHuman Tight MVP

## Metadata

* Date: 2026-09-15
* Related plan: `.copilot-tracking/plans/2026-09-15/ask-my-human-tight-mvp-plan.instructions.md`
* Implementation commit: `9322aa6` (merge of Phase 0 implementation)
* Scope reviewed: Implementation Phase 0 only

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
