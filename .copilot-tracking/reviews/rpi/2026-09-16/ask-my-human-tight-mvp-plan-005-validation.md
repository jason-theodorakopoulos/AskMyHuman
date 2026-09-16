---
title: Tight MVP Documentation and Gate Validation
description: Phase 4 documentation requirements and Phase 5 and 6 implementation inventory review.
ms.date: 2026-09-16
---

## Executive Result

* Validation status: Partial
* Scope: Phase 4 documentation and gate definitions; Phase 5 and 6 inventory
* Verified findings: 7 Major and 3 Minor documentation or validation discrepancies
* Critical product findings: None assessed in this documentation-focused review
* Release acceptance: Not established; local evidence gaps and external gates remain

The ten-command local gate is defined, including 90 percent coverage and strict
typing of source and tests. Documentation, integration, CI, deployment helpers,
and a partial live harness exist. Their existence does not establish completed
Phases 4, 5, or 6. Do not mark later work wholly unimplemented, and do not mark
release gates passed solely because their scripts exist.

The requested `005` filename identifies this output; it does not restrict the
requested review to Phase 5. Findings below concern documentation, test
assertions, and evidence requirements, not a duplicate runtime, infrastructure,
or release-code review.

## Baseline and Method

Read the [plan], [changes log], [primary research], [details], and [planning log]
in full. Inspected the README, environment example, tool configuration, CI,
deployment helper, live module, and relevant test assertions. Enumerated tracked
tests and unlisted implementation surfaces. Current inspected HEAD was `a6756d7`;
the existing user modifications to the plan, changes log, and planning log were
treated as the baseline and preserved.

Retain the [prior Phase 0 product pass]. Its product findings were resolved;
its separate publication limitations are not new product findings here. The
planning log's historical planning-validation pass is likewise not evidence
that subsequent implementation or deployment gates ran.

No pytest, dependency synchronization, full gate, image build, Azure command,
deployment, or live call was run in this review. The user-supplied terminal
context reports a successful focused ASGI test command, not a complete gate.
Only this output was edited. Report checks cover editor diagnostics, local
evidence links, and whitespace, not application correctness.

## Major Findings

### M1 Public Result and Replay Documentation Is Incomplete or Incorrect

[README.md](../../../../README.md#L80) describes `deadline_exceeded` as an
execution error and promises the agent always receives a response. It is a
terminal `expired` outcome, absent from the public
[error-code enum](../../../../src/ask_my_human/errors.py#L7).
The [MCP deadline test](../../../../tests/unit/mcp_adapter/test_server.py#L125)
explicitly asserts `is_error` is false. Cancellation or a closed connection
also makes the unconditional delivery promise inappropriate.

The exclusions at [README.md](../../../../README.md#L23) omit the distinction
between unsupported asynchronous resume and supported subject-scoped
idempotent join/replay. The [research](../../../research/2026-09-15/tight-mvp-scope-research.md#L153)
requires that distinction, and the
[live replay test](../../../../tests/e2e/test_live_call.py#L118) exercises a
repeat invocation after the first response. The guide also omits the
different-payload conflict and one-pending-request admission semantics.

Recommended correction: Describe deadline expiry as an HTTP 200 terminal
result and successful MCP tool result; distinguish technical execution errors.
Document same-key replay/join, changed-payload conflict, and distinct-request
429 behavior without adding asynchronous retrieval or extending the deadline.
Owner: Release/documentation owner with foundation-owner contract review.

### M2 Deployment Runbook Overstates the Helper's Gate Coverage

[README.md](../../../../README.md#L199) lists deployment inputs but omits the
required `AskHuman.Invoke` role assignment and the chosen MCP client's
225-second timeout and cancellation prerequisite. The role is enforced at
[agent.py](../../../../src/ask_my_human/security/agent.py#L60); the unresolved
client requirement is [DR-05](../../../plans/logs/2026-09-15/ask-my-human-tight-mvp-log.md#L31).
These are operator setup requirements, not values that an environment-variable
presence check can approve.

The statement that the helper performs the "whole flow" at
[README.md](../../../../README.md#L213) also overstates the reviewed evidence:

* [run_what_if](../../../../scripts/deploy_azure.sh#L85) discards the change list.
	Successful command completion is not evidence of an operator-reviewed diff.
* [verify_revision](../../../../scripts/deploy_azure.sh#L143) checks image,
	active state, and running state, but not the prescribed `healthState`.
	The smoke helper checks liveness, not readiness. This review does not assess
	whether those checks work against the deployed authentication configuration.
* The helper and README contain no last-known-good rollback procedure or
	first-deployment blocker/diagnostic procedure required by
	[Step 5.2](../../../details/2026-09-15/ask-my-human-tight-mvp-details.md#L1023).

Recommended correction: Label the script as deployment assistance and add the
remaining operator gates, sanitized evidence requirements, and rollback/blocker
instructions. Do not relax authentication or mark a healthy revision verified
to make the documentation true. Coordinate helper defects with its reviewer.
Owner: Release owner and deployment operator.

### M3 The Gate Does Not Exercise the Built Application Container

[Step 4.1](../../../details/2026-09-15/ask-my-human-tight-mvp-details.md#L920)
requires container tests. The [CI image job](../../../../.github/workflows/ci.yml#L52)
validates Compose and builds an image without starting it. The only real
testcontainer is [PostgreSQL](../../../../tests/integration/conftest.py#L13).
The [ASGI fixture](../../../../tests/integration/test_asgi_app.py#L113) uses a
fake use case and spy pool, not the built image or its migration/start command.
No application-container smoke test was found in the tracked test inventory.

Consequently, build success alone does not test the migration-before-Uvicorn
startup promised by [the image](../../../../Dockerfile#L46) or the README's
local health commands. This is a gate coverage gap, not a demonstrated startup
failure. If "container tests" was intended to mean PostgreSQL tests only, that
narrower interpretation needs explicit reconciliation with the startup criteria.

Recommended correction: Record image startup as unverified and have the release
owner add a bounded, non-live startup/migration/health smoke check to the existing
gate, or obtain explicit approval for the narrower acceptance interpretation.
Do not substitute the aggregate 90 percent coverage percentage for this check.

### M4 The Live Matrix Can Pass Without Proving Required Outcomes

[Step 5.3](../../../details/2026-09-15/ask-my-human-tight-mvp-details.md#L1048)
and [Step 6.2](../../../details/2026-09-15/ask-my-human-tight-mvp-details.md#L1099)
require outcome-specific and MCP evidence. The nine live test functions contain
the following narrower assertions:

* [Approval](../../../../tests/e2e/test_live_call.py#L103) accepts either approved
	or rejected; a run need not demonstrate both decisions.
* [Input replay](../../../../tests/e2e/test_live_call.py#L118) checks HTTP 200 and
	equality, not `responded/answered` with nonblank speech. Replaying an expired
	result can satisfy it.
* [Unanswered calling](../../../../tests/e2e/test_live_call.py#L232) accepts five
	expired outcomes. It does not distinguish initial silence, ring-out, busy,
	decline, mid-call disconnect, or a deliberately forced deadline.
* [Cancellation](../../../../tests/e2e/test_live_call.py#L256) asserts only
	`expired`, so deadline expiry can satisfy a test named for cancellation.
* [Idempotency](../../../../tests/e2e/test_live_call.py#L274) proves response
	equality, one database row, and a nonempty correlation, not the number of
	ACS call attempts. It does not exercise an in-flight joined request.
* [_ask](../../../../tests/e2e/test_live_call.py#L88) uses HTTP only. No live MCP
	invocation, MCP cancellation, elapsed-time assertion, or authenticated
	duplicate-callback scenario is implemented in the module.

Recommended correction: Mark these scenarios partial or missing in the
inventory. Tighten named outcome assertions and add missing controlled
scenarios in the existing harness, with provider-side call correlation evidence
where needed. A carrier that cannot expose busy or decline is an external
limitation requiring an approved record; absent test logic is not that limitation.
Owner: Release/test owner. Local unit coverage does not replace live evidence.

### M5 Required Telemetry Evidence Is Optional in the Locked Harness

The [live telemetry test](../../../../tests/e2e/test_live_call.py#L178) calls
`pytest.importorskip("azure.monitor.query")`, but `azure-monitor-query` is absent
from both the declared [development dependencies](../../../../pyproject.toml#L29)
and [uv.lock](../../../../uv.lock#L1). A clean frozen environment therefore does
not declare the query capability required by this release gate and can skip it
even after live execution is explicitly enabled.

The implemented query at [test_live_call.py](../../../../tests/e2e/test_live_call.py#L181)
seeds only prompt content and checks request-ID presence. It does not establish
live sentinel absence for answers, phone numbers, idempotency keys, tokens, and
callback bodies. Existing local sentinel tests are valuable but are different
evidence. No claim is made about packages installed manually in this workspace.

Recommended correction: Route the query dependency and lock update to the
foundation owner. Make required live-evidence prerequisites fail clearly when
explicitly enabled, and enumerate each sensitive category in the acceptance
record. Add a bounded ingestion-readiness policy before judging absence.
Retain the default no-credentials/no-paid-calls guard.

### M6 Tracking Inventory Omits Existing Integration and Release Work

The [changes metadata](../../../changes/2026-09-15/ask-my-human-tight-mvp-changes.md#L9)
lists only Phases 0, 1A, and 1B. Its
[release summary](../../../changes/2026-09-15/ask-my-human-tight-mvp-changes.md#L168)
says Phase 2 composition remains intentionally unimplemented. That is contradicted
by tracked [application composition](../../../../src/ask_my_human/main.py#L1),
[composition tests](../../../../tests/integration/test_asgi_app.py#L1), and
[infrastructure composition](../../../../infra/main.bicep#L1).

Also present but not inventoried are [Dockerfile](../../../../Dockerfile#L1),
[Compose](../../../../compose.yaml#L1), [CI](../../../../.github/workflows/ci.yml#L1),
[deployment tooling](../../../../scripts/deploy_azure.sh#L1), the
[live harness](../../../../tests/e2e/test_live_call.py#L1), and the expanded README.
Infrastructure wiring and release-code correctness remain with their reviewers.

Recommended correction: Append narrow Phase 2 through 5 inventory entries,
including partial implementation and evidence still needed. Retain unchecked
validation/deployment steps until supported by actual results; do not blanket
check phases. Preserve the Phase 0 history, recorded deviations, and current
user edits. Owner: Tracking owner coordinating the named implementation owners.

### M7 Documented-Command Acceptance Creates a Phase-Ordering Conflict

[Step 4.2](../../../details/2026-09-15/ask-my-human-tight-mvp-details.md#L943)
requires every documented command to have run successfully. The README documents
[deployment](../../../../README.md#L222) and [paid live execution](../../../../README.md#L252),
but [Step 5.1](../../../details/2026-09-15/ask-my-human-tight-mvp-details.md#L998)
requires Phase 4, including post-documentation validation, to be complete first.
The supplied artifacts contain neither results satisfying the literal criterion
nor an approved exception to this ordering.

Recommended correction: Explicitly distinguish successfully executed local
commands from documented, externally gated Azure procedures. Obtain approval
to narrow Step 4.2's command-evidence criterion to local validation, retaining
deployment/live acceptance in Phases 5 and 6. Alternatively keep Step 4 partial
until a documented ordering decision exists. Do not fabricate command success
or interpret missing tenant inputs as a product bug. Owner: Plan/release owners.

## Minor Findings

### N1 README Examples and Markdown Miss Required Conventions

The `json` block at [README.md](../../../../README.md#L99) contains an HTTP request
line, so it is not valid JSON. The file lacks the required root-document YAML
`title` and `description`; the [request-flow fence](../../../../README.md#L70)
has no language. The [planning-log path](../../../../README.md#L43) is code text
rather than the navigable link requested by Step 4.2. Several em dashes also
conflict with the applicable writing-style instruction.

Recommended correction: Make the JSON block JSON-only, add compliant frontmatter
with the corresponding heading adjustment, label the flow as `text`, and link
DD-01/follow-on scope. Apply style cleanup only to this documentation surface.

### N2 Configuration Guidance Blurs Host and Compose Settings

[README.md](../../../../README.md#L135) tells readers to create a local environment
file, but [Compose](../../../../compose.yaml#L24) supplies literal placeholder
settings and has no `env_file` binding for the app. Filling in the copied
[.env.example](../../../../.env.example#L1) does not configure that container.
The example does contain all ten required `Settings` fields; optional-field
omission alone is not a defect.

The claim that all settings enter one typed object at
[README.md](../../../../README.md#L160) has an exception:
[observability](../../../../src/ask_my_human/observability.py#L208) reads the
Application Insights connection string directly. The timing settings are also
configurable [defaults](../../../../src/ask_my_human/config.py#L32), whereas the
guide presents the 210-second value as an unconditional invariant.

Recommended correction: Distinguish host-process configuration, placeholder
Compose smoke setup, and live deployment inputs. State the telemetry exception
and supported deployed timing policy without changing frozen settings or
implicitly adding a fake-call mode to Compose.

### N3 The Advertised Full Gate Omits Documentation Revalidation

The [README gate](../../../../README.md#L182) reproduces Step 4.1 but does not
include Step 4.3's post-documentation rerun and Markdown fallback. The
[details](../../../details/2026-09-15/ask-my-human-tight-mvp-details.md#L951)
require editor diagnostics and `git diff --check` for changed Markdown when no
repository Markdown command exists. No repository Markdown validation command
or CI documentation check was found in the inspected configuration.

Recommended correction: Document that fallback and the required post-edit rerun;
record the reviewed revision, results, and any blocker owner/next action. A new
Markdown toolchain is not necessary to satisfy the existing fallback.

## Phase 4 Requirements Matrix

Assessments describe source evidence, not newly executed checks. Every Step 4
checklist entry is covered. There is no Phase 4 completion entry in the supplied
changes log; the matrix below supplies verified matches and remaining gaps.

| ID    | Requirement                                      | Assessment          | Evidence         |
|-------|--------------------------------------------------|---------------------|------------------|
| 4.1a  | Ten local commands from a clean checkout          | Defined; unverified | [G], [CI], [D41] |
| 4.1b  | Schema, format, lint, strict source/test typing   | Defined; unverified | [G], [Tools]     |
| 4.1c  | Non-live tests with at least 90 percent coverage  | Defined; unverified | [Coverage], [CI] |
| 4.1d  | Contract, state, race, auth, redaction tests       | Files present       | [Test evidence]  |
| 4.1e  | ASGI composition and migration tests              | Files present       | [ASGI], [PG]     |
| 4.1f  | Container tests                                  | Partial; M3         | [Image CI]       |
| 4.1g  | No excluded-scope dependencies or resources       | Scope aligned       | [Scope], [Log]   |
| 4.1h  | Isolated fixes stay with their owning workstreams | No fixes attempted  | [D41]            |
| 4.2a  | Document only after pre-documentation gate        | Evidence missing    | [Changes], [D42] |
| 4.2b  | One turn, canonical name, architecture, DD-01      | Documented          | [Scope]          |
| 4.2c  | Request and result examples, 210-second semantics | Partial; M1, N1     | [API docs]       |
| 4.2d  | Local setup and required configuration            | Partial; N2         | [Setup], [Env]   |
| 4.2e  | Validation commands and successful executions     | Defined; M7         | [G], [D42]       |
| 4.2f  | Azure prerequisites and deployment flow           | Partial; M2         | [Deploy docs]    |
| 4.2g  | Explicit exclusions and linked follow-on work     | Partial; M1, N1     | [Scope], [Log]   |
| 4.2h  | No secrets or real tenant identifiers in examples | Placeholder-only    | [Env], [Setup]   |
| 4.3a  | Complete gate rerun after documentation edits     | Evidence missing    | [D43], [Changes] |
| 4.3b  | Live module safe by default and linted/typed      | Defined; unexecuted | [Live guard], [G]|
| 4.3c  | Markdown diagnostics, links, and whitespace       | Gaps; N1, N3        | [D43], [G]       |
| 4.3d  | Fix/rerun or record blocker with owner/action     | Actions recorded    | [D43]            |

For 4.1g, the documented exclusions and manifest match the selected tight scope;
this is not certification of the lockfile, image contents, or deployed resource
graph. Those required artifact checks remain with the other reviewers and gates.
For 4.3d, this output records findings and owners, but does not substitute for
the release owner's final blocker disposition.

### Gate Definition Audit

All ten Step 4.1 commands occur in the README. CI has matching lock, frozen
sync, schema, formatting, lint, typing, and coverage steps; Compose validation
and the image-build action provide the image-stage equivalents. CI additionally
compiles module and parameter files with placeholders. No application-container
execution or Markdown fallback is supplied by those stages.

[pyproject.toml](../../../../pyproject.toml#L46) defines default `not live`
selection and the live marker. Coverage uses `branch = true`, package source
selection, `fail_under = 90`, and missing-line reporting. The documented/CI
pytest command actually enables coverage; bare focused pytest does not.
Strict mypy targets both source and tests with no live-module exclusion, and
Ruff's whole-repository commands include that module.

No coverage-threshold omission or live-module typing exclusion was found.
The [150-test Phase 1 result](../../../changes/2026-09-15/ask-my-human-tight-mvp-changes.md#L149)
does not report current aggregate coverage and is not a Phase 4 or final gate
result. No current coverage percentage is asserted here.

### Non-Live Test Evidence

The required categories have existing homes: [contract tests], [domain tests],
[repository race tests], [security tests], [redaction tests], [ASGI], and
[migration tests]. The local suite also contains
[callback-redelivery tests](../../../../tests/unit/api/test_callbacks.py#L113)
and [deadline tests](../../../../tests/unit/application/test_service.py#L39).
This verifies test presence, not execution success or live equivalence.

## Phase 5 and 6 Inventory

All six plan steps were compared with the changes log. None has a corresponding
completion entry there. Recommended inventory states are:

| Step | Implemented or defined                          | Still needed                              | State                |
|------|-------------------------------------------------|-------------------------------------------|----------------------|
| 5.1  | Environment checks and what-if helper            | DR resolutions and reviewed diff evidence | Partial; external    |
| 5.2  | ACR build, deploy, revision/auth helpers         | Healthy revision and failure-path record  | Partial; unverified  |
| 5.3  | Guarded nine-test HTTP/database live module      | Complete matrix and actual live evidence  | Partial; gaps M4/M5  |
| 6.1  | Final rerun procedure and reusable local commands| Final-state gate; what-if after infra edit| Defined; unexecuted  |
| 6.2  | Release-evidence acceptance criteria             | Per-requirement evidence and exceptions   | Defined; incomplete  |
| 6.3  | Owner-scoped corrections/blocker procedure       | Disposition, owners, reruns, and handoff  | Defined; incomplete  |

Step 5.1 evidence is [the helper](../../../../scripts/deploy_azure.sh#L45) and
[DR-01 through DR-05](../../../plans/logs/2026-09-15/ask-my-human-tight-mvp-log.md#L9).
Step 5.2 helpers start at [build_image](../../../../scripts/deploy_azure.sh#L95);
M2 lists the difference between their presence and the complete acceptance gate.
Steps 6.1, 6.2, and 6.3 are defined in
[the final phase](../../../details/2026-09-15/ask-my-human-tight-mvp-details.md#L1084),
not recorded as executed in the supplied tracking artifacts.

### Live Scenario Inventory

| Required evidence                       | Source coverage                        | Assessment                 |
|-----------------------------------------|----------------------------------------|----------------------------|
| Approval and rejection separately        | Either decision in [Live approval]      | Partial                    |
| Nonblank spoken free-form answer         | Input request in [Live replay]          | Missing answer assertion   |
| Initial silence and unanswered ringing   | Broad expiry in [Live unanswered]      | Partial                    |
| Busy/decline when carrier exposes them   | Allowed outcomes in [Live unanswered]   | No controlled cases        |
| Mid-call disconnect                     | Allowed outcome in [Live unanswered]    | No controlled case         |
| Initiating-client cancellation outcome   | Expired state in [Live cancellation]    | Partial                    |
| Forced deadline and elapsed bound       | Allowed outcome; HTTP timeout is 240 s  | No controlled/bounded proof|
| Idempotent replay                       | Equality in [Live replay]               | Implemented; unexecuted     |
| Duplicate callback and terminal race     | No live scenario                       | Missing live evidence path |
| One actual call and one terminal row     | Row count/call ID in [Live idempotency]  | Partial                    |
| MCP result, timeout, and cancellation    | HTTP-only [_ask]                       | Missing live evidence path |
| Absence of all sensitive telemetry      | Prompt query in [Live telemetry]        | Partial; dependency skips  |
| Accelerated retention via normal purge  | Backdated and retained rows in [Purge]  | Implemented; unexecuted     |

[Purge] uses `RequestMaintenance.purge_once()` with a controlled backdated
terminal row and a recent retained row. This is a genuine implemented match to
the retention requirement, not a 24-hour waiting placeholder. The module-level
[Live guard] and marker configuration are also implemented matches; this review
did not collect or execute them.

## Scope Reconciliation

Preserve DD-01 (Play and Recognize instead of Voice Live), DD-02 (one replica),
DD-03 (durable internal technical-error replay), DD-04 (cross-scope support
modules), and DD-05 (public endpoints). These are recorded decisions, not new
defects or invitations to restore private networking or add an audio relay.

The README correctly documents DD-01 and DD-05. Its claim that private
networking is tracked as follow-on work should point specifically to DD-05 or
be narrowed: the [WI list](../../../plans/logs/2026-09-15/ask-my-human-tight-mvp-log.md#L126)
contains no private-networking work item. Do not create a new feature commitment
merely to reconcile that sentence.

The primary research's original no-implementation snapshot and naming question
are historical context. Use the current plan, recorded decisions, and verified
files for inventory. Do not rewrite historical Phase 0 conclusions or remove
the user's active tracking changes.

## Evidence Blockers and Recommended Next Validations

DR-01 through DR-04 depend on an eligible numbered ACS resource, tenant/app
identities and roles, retention approval, and subscription/region/registry
permissions. No approved values or exceptions appear in the supplied log.
Missing repository evidence does not prove the operator lacks these resources.

DR-05 combines an external client choice with missing verification: credentials
alone will not add the absent MCP test path. Carrier busy/decline limitations
are external only after an attempted scenario establishes the limitation.
Unexecuted local gates, undeclared query dependencies, and weak assertions are
not tenant blockers and should not be classified as product runtime failures.

* [ ] Release/documentation owner: Correct M1/M2 and N1/N2 in the existing README;
	preserve selected architecture and avoid new feature scope
* [ ] Plan/tracking owners: Approve M7's local-versus-Azure evidence split and
	append the narrow implemented/partial/unverified inventory from M6
* [ ] Release/test owner: Resolve the application-container smoke criterion and
	complete the named live assertions without introducing paid CI execution
* [ ] Foundation/release owners: Declare the telemetry-query dependency and
	ensure explicitly enabled mandatory evidence cannot silently skip
* [ ] Local gate owner: Run all ten commands against the reviewed clean state,
	record coverage, then rerun after documentation changes with Markdown checks
* [ ] Deployment operator: Resolve DR inputs, review sanitized what-if output,
	verify exact image/revision/readiness/authentication, and record rollback policy
* [ ] Live-test owner: Run the completed HTTP/MCP matrix only against the verified
	revision; retain sanitized call, terminal-row, telemetry, and purge evidence
* [ ] Release owner: Perform final Step 6.1 reruns, conditional what-if, Step 6.2
	evidence review, and an explicit release-ready or blocked disposition

All listed execution validations remain unperformed in this session by request.
Each proposed product, test, dependency, or tracking edit is a recommendation,
not a change made by this reviewer.

## Clarifying Questions

* Do the plan and release owners approve limiting Step 4.2 command-success
	evidence to local commands while Azure procedures remain gated in Phase 5?
* Where should sanitized DR approvals, the reviewed what-if decision, exact
	deployment revision, live outcomes, and any carrier exceptions be recorded?
* Does the intended container-test criterion require the built application's
	startup smoke test, or was a narrower interpretation explicitly approved?

No secret values are requested. Answers affect acceptance and evidence records,
not authorization to expand the product scope.

## Coverage Assessment

All three Phase 4 checklist items and their detailed requirements were compared;
all six Phase 5/6 steps and all named live scenarios were inventoried. Seven major
and three minor findings explain why this is Partial rather than Passed.
The source-defined local gate is substantially present, Phase 4 documentation
needs correction, Phase 5 helpers are partly implemented, and Phase 6 acceptance
remains without execution evidence. No completion percentage or runtime pass is
inferred from static inspection.

[plan]: ../../../plans/2026-09-15/ask-my-human-tight-mvp-plan.instructions.md
[changes log]: ../../../changes/2026-09-15/ask-my-human-tight-mvp-changes.md
[primary research]: ../../../research/2026-09-15/tight-mvp-scope-research.md
[details]: ../../../details/2026-09-15/ask-my-human-tight-mvp-details.md
[planning log]: ../../../plans/logs/2026-09-15/ask-my-human-tight-mvp-log.md
[prior Phase 0 product pass]: ../2026-09-15/ask-my-human-tight-mvp-plan-000-validation.md#L9
[G]: ../../../../README.md#L186
[CI]: ../../../../.github/workflows/ci.yml#L30
[D41]: ../../../details/2026-09-15/ask-my-human-tight-mvp-details.md#L896
[D42]: ../../../details/2026-09-15/ask-my-human-tight-mvp-details.md#L923
[D43]: ../../../details/2026-09-15/ask-my-human-tight-mvp-details.md#L951
[Tools]: ../../../../pyproject.toml#L60
[Coverage]: ../../../../pyproject.toml#L52
[Test evidence]: #non-live-test-evidence
[ASGI]: ../../../../tests/integration/test_asgi_app.py#L192
[PG]: ../../../../tests/integration/conftest.py#L13
[Image CI]: ../../../../.github/workflows/ci.yml#L52
[Scope]: ../../../../README.md#L8
[Log]: ../../../plans/logs/2026-09-15/ask-my-human-tight-mvp-log.md#L37
[Changes]: ../../../changes/2026-09-15/ask-my-human-tight-mvp-changes.md#L145
[API docs]: ../../../../README.md#L83
[Setup]: ../../../../README.md#L129
[Env]: ../../../../.env.example#L1
[Deploy docs]: ../../../../README.md#L199
[Live guard]: ../../../../tests/e2e/test_live_call.py#L25
[contract tests]: ../../../../tests/contract/test_json_schemas.py#L26
[domain tests]: ../../../../tests/unit/domain/test_transitions.py#L17
[repository race tests]: ../../../../tests/integration/persistence/test_repository.py#L94
[security tests]: ../../../../tests/unit/security/test_acs_callback.py#L73
[redaction tests]: ../../../../tests/unit/test_observability.py#L153
[migration tests]: ../../../../tests/integration/persistence/test_migrations.py#L4
[Live approval]: ../../../../tests/e2e/test_live_call.py#L103
[Live replay]: ../../../../tests/e2e/test_live_call.py#L118
[Live unanswered]: ../../../../tests/e2e/test_live_call.py#L232
[Live cancellation]: ../../../../tests/e2e/test_live_call.py#L256
[Live idempotency]: ../../../../tests/e2e/test_live_call.py#L274
[_ask]: ../../../../tests/e2e/test_live_call.py#L88
[Live telemetry]: ../../../../tests/e2e/test_live_call.py#L174
[Purge]: ../../../../tests/e2e/test_live_call.py#L133