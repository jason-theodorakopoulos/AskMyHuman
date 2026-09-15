---
title: AskMyHuman Tight MVP Phase 0 Final Validation
description: Final RPI validation of corrected implementation Phase 0 against the plan, changes, and research
ms.date: 2026-09-15
ms.topic: reference
---

## Executive Result

* Phase: 0, Foundation and Contract Freeze
* Implementation under review: commit `9322aa6` plus the current second correction set
* Validation status: Partial
* Product implementation status: Passed
* Critical implementation findings: 0
* Major implementation findings: 0
* Minor implementation findings: 0
* Explicit Phase 0 criteria assessed: 21
* Fully satisfied: 18
* Partially satisfied: 1
* Incomplete process criteria: 2
* Product implementation coverage: 100 percent
* Overall fully satisfied coverage: 85.7 percent

All implementation criteria in Steps 0.1 through 0.4 are satisfied by the
current worktree. The second correction set resolves the remaining request
contract parity and settings error-redaction defects, and focused tests prove
both behaviors. The complete corrected local gate passes with 47 tests.

The overall result remains Partial because Step 0.5 requires validation from a
clean checkout, publication of the reviewed corrected foundation commit, and
communication of that hash to every workstream owner. The correction set is
not committed. This is an incomplete publication process, not a product-code
defect. This validation does not create a commit because no explicit commit
authorization was provided.

## Artifact Scope

The validation read the Phase 0 implementation plan, detailed implementation
criteria, planning log, changes log, primary research, corrected parallel
layout research, prior validation, and current implementation files. It also
checked all current paths changed from `9322aa6`, searched for unlisted
Phase 0-related changes, and reran the complete corrected gate.

Current `HEAD` is `9322aa6` on `main` and `origin/main`. The changes log still
identifies that hash as the implementation commit at
[the changes log](../../../changes/2026-09-15/ask-my-human-tight-mvp-changes.md#L8),
while its correction section remains pending at
[the end of the changes log](../../../changes/2026-09-15/ask-my-human-tight-mvp-changes.md#L50-L52).

## Requirements Matrix

### Step 0.1 Python Package And Dependency Baseline

1. Passed: `uv lock --check` resolves 114 packages without changing the lock.
2. Passed: `uv sync --frozen --all-groups` checks all 111 installed packages.
3. Passed: Python is constrained to `>=3.12,<3.13` in
   [pyproject.toml](../../../../pyproject.toml#L6), with the local version pinned
   to 3.12 in [.python-version](../../../../.python-version#L1).
4. Passed: No requirements, Poetry, Pipenv, PDM, or tox dependency workflow was
   found.

### Step 0.2 Configuration And Public Contracts

1. Passed: Approval, input, responded, expired, and execution-error examples
   validate against the checked-in schemas.
2. Passed: Unknown fields and invalid result discriminator combinations are
   rejected. The generated result schema uses `oneOf` at
   [ask-human-result.schema.json](../../../../schemas/ask-human-result.schema.json#L29),
   with schema-level negative cases in
   [test_json_schemas.py](../../../../tests/contract/test_json_schemas.py#L67-L90).
3. Passed: Pydantic and JSON Schema now reject the same overlong raw wire
   prompt. The before-validator rejects raw values over 2,000 characters at
   [contracts.py](../../../../src/ask_my_human/contracts.py#L42-L49), before
   whitespace normalization can shorten them. The boundary parity test is at
   [test_json_schemas.py](../../../../tests/contract/test_json_schemas.py#L100-L110).
4. Passed: Settings representations and validation errors exclude secret
   values. Phone values remain `SecretStr`, and
   `hide_input_in_errors=True` is configured at
   [config.py](../../../../src/ask_my_human/config.py#L11-L16). Invalid E.164
   tests assert that the submitted value is absent from the error at
   [test_config.py](../../../../tests/unit/test_config.py#L44-L50).
5. Passed: `uv run python scripts/export_schemas.py --check` succeeds. The
   deterministic exporter and result discriminator augmentation are in
   [export_schemas.py](../../../../scripts/export_schemas.py#L11-L57).

These checks satisfy the explicit contract parity and redaction requirements in
[Step 0.2](../../../details/2026-09-15/ask-my-human-tight-mvp-details.md#L118-L125).

### Step 0.3 Domain State And Application Ports

1. Passed: Domain modules contain no FastAPI, MCP, Psycopg, Azure, or
   OpenTelemetry imports.
2. Passed: All researched event-to-outcome mappings are typed in
   [models.py](../../../../src/ask_my_human/domain/models.py#L15-L25) and mapped
   in [transitions.py](../../../../src/ask_my_human/domain/transitions.py#L6-L17).
3. Passed: A terminal request cannot transition again at
   [transitions.py](../../../../src/ask_my_human/domain/transitions.py#L43-L47),
   with focused coverage in
   [test_transitions.py](../../../../tests/unit/domain/test_transitions.py#L61-L78).
4. Passed: The shared fakes support deterministic time, independent
   cancellation, replay and conflict admission, first-terminal arbitration,
   call actions, and typed telemetry. Implementations begin in
   [fakes.py](../../../../tests/support/fakes.py#L24), with focused behavior
   tests in [test_fakes.py](../../../../tests/unit/test_fakes.py#L37-L129).
5. Passed: The inbound use-case accepts a cancellation signal, and the use-case,
   repository, gateway, clock, cancellation, and telemetry protocols are frozen
   in [ports.py](../../../../src/ask_my_human/application/ports.py#L26-L101).
   The fake use case implements that protocol at
   [fakes.py](../../../../tests/support/fakes.py#L50-L72).
6. Passed: Strict mypy succeeds for contracts, domain, ports, configuration,
   fakes, and fake tests with no issues in 8 checked files.

### Step 0.4 Infrastructure Module Contracts

1. Passed by source inspection: `infra/main.bicep` freezes inputs and outputs
   for identity, network, observability, PostgreSQL, communications, and
   Container App modules at
   [main.bicep](../../../../infra/main.bicep#L44-L73).
2. Passed by source inspection: PostgreSQL credentials, both phone numbers, and
   the Microsoft Entra client secret are secure parameters at
   [main.bicep](../../../../infra/main.bicep#L15-L35). PostgreSQL outputs exclude
   credentials and a complete DSN.
3. Passed by source inspection: Existing ACS, Microsoft Entra, and container
   registry selections remain external inputs. Environment bindings are in
   [dev.bicepparam](../../../../infra/environments/dev.bicepparam#L3-L14), and
   module owners can implement the documented contracts without changing the
   composition root.

Bicep compilation remains unverified because neither Azure CLI nor standalone
Bicep CLI is installed. This limitation is reported as a tooling gap rather
than an implementation finding.

### Step 0.5 Validation And Publication

1. Partially satisfied: Every prescribed and expanded command passes against
   the current worktree. The success criterion requires those commands to pass
   from a clean checkout at
   [Step 0.5](../../../details/2026-09-15/ask-my-human-tight-mvp-details.md#L217-L235).
   A clean checkout cannot contain the uncommitted correction set, so that part
   remains unverified until publication.
2. Incomplete process criterion: No reviewed corrected foundation commit has
   been created or published. `9322aa6` predates the current corrections.
3. Incomplete process criterion: No corrected foundation hash exists to
   communicate to every workstream owner, and no communication artifact was
   found.

The absence of a new commit and hash is not classified as a product-code
defect. Creating a commit requires explicit user authorization outside this
validation request.

## Implementation Findings

### Critical

No critical implementation findings.

### Major

No major implementation findings.

### Minor

No minor implementation findings.

## Unverified Process Criteria

1. Clean-checkout reproduction is unverified. The green gate covers the exact
   current worktree, but the correction set has no commit from which a clean
   checkout can be created.
2. Foundation publication is incomplete. Current `HEAD` and `origin/main` remain
   at `9322aa6`.
3. Workstream-owner notification is unverified because no corrected hash or
   distribution record exists.

## Tooling Gaps

1. `az bicep build --file infra/main.bicep` was not run because Azure CLI is
   unavailable.
2. A standalone `bicep build infra/main.bicep` fallback was not run because the
   Bicep CLI is also unavailable.

Source inspection supports all Step 0.4 criteria, but compilation should still
be completed when either supported tool becomes available.

## Evidence Discrepancy

### Minor Documentation Finding

The changes log does not describe either correction set, the current changed
file set, or the final 47-test result. It still says review corrections are
pending at
[ask-my-human-tight-mvp-changes.md](../../../changes/2026-09-15/ask-my-human-tight-mvp-changes.md#L50-L52).
This is an evidence-maintenance gap, not a product implementation defect.

## Executable Evidence

The following combined gate passed against the current worktree:

* `uv lock --check`, 114 packages resolved
* `uv sync --frozen --all-groups`, 111 packages checked
* `uv run python scripts/export_schemas.py --check`
* Focused pytest suite, 47 passed
* Strict mypy target, no issues in 8 checked files
* Ruff format check, 23 files already formatted
* Ruff lint check, all checks passed
* `git diff --check`

The pytest run includes the raw overlength wire-prompt parity test and the
invalid-phone validation-error redaction tests. These directly disconfirm the
two product defects from the preceding validation.

## Coverage Assessment

Steps 0.1 through 0.4 are complete: all 18 product implementation criteria are
verified, for 100 percent product implementation coverage. No critical, major,
or minor implementation finding remains.

Across all 21 Phase 0 criteria, 18 are fully satisfied, one is partially
satisfied, and two publication criteria are incomplete. Overall fully satisfied
coverage is 85.7 percent. Phase 0 is therefore Partial until the correction set
is explicitly authorized for commit, published as the reviewed foundation, and
communicated to workstream owners.

## Clarifying Questions

* Which artifact or channel should record distribution of the corrected
  foundation hash to every workstream owner after publication?

No clarification is required for the Phase 0 product implementation.

## Recommended Next Validations

* [ ] After explicit authorization, commit and publish the complete correction
  set as the reviewed Phase 0 foundation
* [ ] Rerun the complete gate from a separate clean checkout of that commit
* [ ] Record communication of the corrected foundation hash to every workstream
  owner
* [ ] Update the changes log with both correction sets and final gate evidence
* [ ] Compile `infra/main.bicep` when Azure CLI or Bicep CLI is available
