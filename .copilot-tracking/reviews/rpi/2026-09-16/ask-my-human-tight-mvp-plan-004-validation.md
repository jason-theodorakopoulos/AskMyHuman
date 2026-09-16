---
title: Phase 3 Image Compose CI and Live Harness Validation
description: Review-only validation of the Phase 3 implementation against the tight MVP plan and supporting requirements.
ms.date: 2026-09-16
---

## Executive Assessment

Status: Failed.

Phase 3 is implemented in part, not absent: all six requested files exist and
are Git-tracked. The CI command inventory substantially matches the plan.
However, image startup can fail and disclose a database URL, runtime access
logs can retain sensitive query values, local MCP rejects the configured port,
and the live harness can skip required evidence or accept incorrect outcomes.
The deployment helper also contains release-gating defects.

Findings: eight Critical, five Major, and one Minor. These are source-level
findings with concrete reproductions to implement, not claims of observed Azure
failures. External release acceptance remains blocked independently of these
code-fixable defects.

## Scope and Evidence

The requested through-line is Phase 3, Steps 3.1 through 3.3. The user-requested
`004` filename suffix does not change that scope to Phase 4. The deployment
helper is explicitly included by the request; its applicable Step 5 requirements
are assessed as supporting release prerequisites, not additional Phase 3 steps.

Reviewed revision: `a6756d741f736560f79e510cbcb0fbd0e90d3b18`, with the current
working copies of the supplied planning artifacts. Existing plan, changes-log,
planning-log, and other review changes were preserved. A scoped Git diff showed
no working-tree differences in the reviewed implementation slice. Only this
validation document was edited.

All five supplied context artifacts were read in full:

* P: [Implementation plan](.copilot-tracking/plans/2026-09-15/ask-my-human-tight-mvp-plan.instructions.md#L195), including every Phase 3 checklist item and shared ownership rules
* C: [Changes log](.copilot-tracking/changes/2026-09-15/ask-my-human-tight-mvp-changes.md#L9), which records only Phases 0, 1A, and 1B
* R: [Primary research](.copilot-tracking/research/2026-09-15/tight-mvp-scope-research.md#L1), including synchronous timing, one-call semantics, privacy, and retention
* D: [Implementation details](.copilot-tracking/details/2026-09-15/ask-my-human-tight-mvp-details.md#L817), including Steps 3.1, 3.2, 3.3 and the referenced live matrix
* L: [Planning log](.copilot-tracking/plans/logs/2026-09-15/ask-my-human-tight-mvp-log.md#L11), including DR-01 through DR-05 and accepted deviations

Source identifiers used in the matrices:

* S1: [Dockerfile](Dockerfile)
* S2: [.dockerignore](.dockerignore)
* S3: [compose.yaml](compose.yaml)
* S4: [.github/workflows/ci.yml](.github/workflows/ci.yml)
* S5: [tests/e2e/test_live_call.py](tests/e2e/test_live_call.py)
* S6: [scripts/deploy_azure.sh](scripts/deploy_azure.sh)

Nearby implementation reads were limited to the startup, authentication,
configuration, telemetry, repository, and maintenance paths needed to verify
these files. Installed Alembic, Uvicorn, MCP, and Python ConfigParser source was
read to verify library behavior. No Python environment was reconfigured and no
package was installed. No implementation or live-test code was executed.

## Requirement Matrix

Every Phase 3 checklist entry is unchecked in P and has no corresponding entry
in C. The following statuses assess actual implementation separately. `Present`
means verified in source, not a passing runtime or CI execution. Evidence notation
such as `S1:16` identifies the source inventory above and a 1-based line.

### Step 3.1 Image and Local Environment

Requirements: [D Step 3.1](.copilot-tracking/details/2026-09-15/ask-my-human-tight-mvp-details.md#L817).
Changes-log match: none. Overall code coverage: Partial.

| ID    | Requirement                              | Evidence                 | Assessment                         |
|-------|------------------------------------------|--------------------------|------------------------------------|
| 31-01 | Python 3.12 slim-bookworm reviewed digest | S1:2, S1:25              | Missing digest; F08                 |
| 31-02 | Pinned uv                                | S1:4                     | Present: version 0.12.0             |
| 31-03 | Multistage, locked production install    | S1:13, S1:16, S1:22      | Present: frozen and no-dev          |
| 31-04 | Migrate serially before one worker       | S1:46                    | Present command; startup bug F01    |
| 31-05 | No second deployable runtime process    | S1:46                    | Present: shell exec after Alembic   |
| 31-06 | No dev packages or local secrets         | S1:36, S2:1, S2:20       | Source exclusions present          |
| 31-07 | Local PostgreSQL and app wiring          | S3:2, S3:20, S3:26       | Present; MCP and exposure F09/F10   |
| 31-08 | Compose config parses                   | S3                       | Scoped parser check passed         |
| 31-09 | Image builds from clean checkout         | S4:63                    | CI gate exists; build not run here  |
| 31-10 | Runtime preserves content-free logging  | S1:46                    | Access-log and startup leaks F01/02 |

Both stages use the production dependency group, and the final stage copies only
the venv, source, migration files, and Alembic configuration. The uv executable
remains in the builder. The final image runs as UID 10001. These are positive
source findings, not an inspected final image inventory. Uvicorn defaults to one
worker in the supplied configuration; an explicit worker count would remove
environment-dependent ambiguity.

### Step 3.2 Continuous Integration

Requirements: [D Step 3.2](.copilot-tracking/details/2026-09-15/ask-my-human-tight-mvp-details.md#L848)
and [local merge-gate commands](.copilot-tracking/details/2026-09-15/ask-my-human-tight-mvp-details.md#L896).
Changes-log match: none. Overall code coverage: Present, execution unverified.

| ID    | Requirement                              | Evidence                 | Assessment                         |
|-------|------------------------------------------|--------------------------|------------------------------------|
| 32-01 | Pinned uv and lock freshness             | S4:16, S4:27, S4:31      | Present                            |
| 32-02 | Frozen complete development environment  | S4:34                    | Present: frozen and all-groups      |
| 32-03 | Generated schema drift                   | S4:37                    | Present                            |
| 32-04 | Format and lint                          | S4:40, S4:43             | Present                            |
| 32-05 | Strict typing including live module      | S4:46                    | Present: src and tests              |
| 32-06 | Non-live tests and 90 percent coverage   | S4:50                    | Present: explicit exclusion/limit   |
| 32-07 | Compose configuration gate               | S4:59                    | Present                            |
| 32-08 | Image build without publication          | S4:63, S4:66             | Present; image is not run           |
| 32-09 | Bicep build                              | S4:85, S4:90             | Present: modules and parameters     |
| 32-10 | No paid Azure calls in normal CI         | S4:50, S4:66             | Present: no live or deploy step     |

The parameter-build job supplies all environment names consumed by
[the parameter file](infra/environments/dev.bicepparam#L3), using obvious
compile-only placeholders. No real credentials were found in the reviewed CI,
Compose, or Docker literals. All local merge-gate command categories are
represented in CI. This review does not claim those checks pass or are required
by branch protection. Build-only validation does not catch F01, F02, or F09.

### Step 3.3 Gated Live Harness

Requirements: [D Step 3.3](.copilot-tracking/details/2026-09-15/ask-my-human-tight-mvp-details.md#L869),
[D live scenario matrix](.copilot-tracking/details/2026-09-15/ask-my-human-tight-mvp-details.md#L1048),
and [D release evidence](.copilot-tracking/details/2026-09-15/ask-my-human-tight-mvp-details.md#L1099).
Changes-log match: none. Overall code coverage: Partial with false positives.

| ID    | Requirement                              | Evidence                 | Assessment                         |
|-------|------------------------------------------|--------------------------|------------------------------------|
| 33-01 | Every test marked live                   | S5:25                    | Present: module-wide marker         |
| 33-02 | Explicit live opt-in                     | S5:28                    | Present: exact environment value    |
| 33-03 | Credential-free default collection       | S5:58, S5:68, S5:78      | Present structure; not executed     |
| 33-04 | Included in Ruff and mypy                | S4:40, S4:43, S4:46      | Present command scope               |
| 33-05 | Verified revision before any paid call   | S5:68, S5:103, S6:218    | No enforced linkage; F04            |
| 33-06 | Separate approval and rejection proof   | S5:114                   | Either outcome passes; F05          |
| 33-07 | Nonblank free-form answer               | S5:123, S5:130           | Input replay only; F05              |
| 33-08 | Silence and unanswered distinction      | S5:232, S5:243           | Broad expired set only; F05         |
| 33-09 | Busy/decline where carrier exposes them  | S5:245, S5:246           | Accepted alternatives, not cases    |
| 33-10 | Mid-call disconnect                     | S5:247                   | No dedicated case; F05              |
| 33-11 | Initiating-client cancellation           | S5:264, S5:271           | Any expired outcome passes; F05     |
| 33-12 | Forced deadline and 210-second bound     | S5:33, S5:307            | No exact timing assertions; F05     |
| 33-13 | MCP result, timeout, and cancellation   | S5:88                    | HTTP only; F05                      |
| 33-14 | Replay and one actual call attempt       | S5:130, S5:289, S5:296   | JSON/row checks insufficient; F05   |
| 33-15 | Duplicate callbacks cannot rewrite state| S5                       | No duplicate-callback scenario      |
| 33-16 | Terminal DB result matches wire result   | S5:95, S5:253            | Partial fields checked; F05          |
| 33-17 | Correlation and all sensitive sentinels  | S5:178, S5:196, S5:202   | Optional and incomplete; F06        |
| 33-18 | Controlled backdated row, normal purge  | S5:137, S5:141, S5:144   | Correct path; race/cleanup F13       |
| 33-19 | No 24-hour sleep or production test hook| S5:148                   | Present                            |

The default pytest configuration in [pyproject.toml](pyproject.toml#L49) excludes
`live`; module-level `skipif` adds a second guard if selection is overridden.
Credentials are requested inside fixtures/test bodies, not during import.
That safety structure is credited without executing collection or live tests.

## Critical Findings

### F01 Encoded database passwords break image startup and expose the DSN

Evidence: [Docker startup](Dockerfile#L46),
[Alembic URL assignment](migrations/env.py#L13), and
[Azure DSN construction](infra/modules/container-app.bicep#L144).

The deployed password is URI-encoded, but Alembic passes the resulting URL
directly to `Config.set_main_option`. Installed Alembic delegates to
`ConfigParser.set` and explicitly requires `%%` for literal percent characters.
Python's `BasicInterpolation.before_set` rejects an unescaped `%40`, `%25`, or
similar escape and includes the entire supplied value in its `ValueError`.
The uncaught migration error stops the `&&` chain before Uvicorn starts and can
print the credential-bearing URL to container stderr.

Concrete reproduction, not executed: give the migration configuration a dummy
URL containing `dummy%40password`; it fails at configuration assignment before
opening a database connection. This does not require a valid database or Azure.
An ordinary password containing `@` reaches this path after Bicep encoding.

Fix: have the migration owner escape percent characters at the ConfigParser
boundary, or pass a SQLAlchemy URL through an API that does not interpolate it.
Preserve URI encoding for the driver. Add an offline dummy-URL regression for
special characters and assert startup error output never contains the DSN or
password. The release owner must include that regression in image-startup proof.

### F02 Default Uvicorn access logs disclose sensitive query content

Evidence: [Docker command](Dockerfile#L46),
[observability configuration](src/ask_my_human/observability.py#L212), and
[container log destination](infra/modules/container-app.bicep#L94).

The command leaves Uvicorn access logging enabled. Installed Uvicorn defaults
`access_log` to true and logs `get_path_with_query_string(scope)` for every
response. Application span allowlisting does not sanitize this independent
logger, and the deployment forwards container console logs to Log Analytics.

Concrete reproduction, not executed: send an invalid-token, empty callback
request to `/v1/callbacks/acs?token=PHASE3_QUERY_SENTINEL` on a local container.
It requires no outbound call; the 401 access-log line still includes the query
sentinel. This establishes a disclosure path for sensitive values in URLs,
not an assertion that request bodies or Authorization headers are logged.

Fix: disable default access logs in the runtime command, or install a logger
that emits only the approved fields and excludes raw paths/query strings.
Capture actual server stdout/stderr in a regression, not only application spans.
Check framework auto-instrumentation separately for equivalent URL attributes.

### F03 Deployment verification rejects a correctly protected health route

Evidence: [anonymous liveness check](scripts/deploy_azure.sh#L185),
[sole Entra exclusion](infra/modules/container-app.bicep#L288), and
[internal readiness probe](infra/modules/container-app.bicep#L253).

The script expects HTTP 200 for an anonymous public `/health/live` request.
The reviewed auth configuration excludes only the ACS callback route and uses
`Return401` everywhere else. A correctly configured public ingress therefore
returns 401 and causes both deployment verification modes to fail, even when
internal probes succeed.

Concrete reproduction, not executed: stub the three negative auth checks with
their expected 401 responses and the public health route with its required 401.
Verification fails at the final health assertion. No Azure access is needed.

Fix: preserve the sole callback exclusion. Validate internal probe state through
Azure metadata or use an authenticated health request. Do not make health public
to satisfy this script. Add shell tests for the intended protected-ingress case.

### F04 Live opt-in does not enforce release or authentication preflight

Evidence: [live guard](tests/e2e/test_live_call.py#L25),
[client fixture](tests/e2e/test_live_call.py#L68),
[first call scenario](tests/e2e/test_live_call.py#L103),
[later smoke tests](tests/e2e/test_live_call.py#L205), and
[deployment success message](scripts/deploy_azure.sh#L218).

`RUN_LIVE_AZURE_TESTS=1` establishes cost consent, but no fixture verifies the
reviewed image, active/healthy revision, public endpoint, or prior auth checks.
The client accepts any supplied base URL, including HTTP. Under default ordering,
paid scenarios run before the smoke tests. Selecting a call with `-k` omits those
checks entirely; a smoke failure also does not stop subsequent calls by default.
There is no linkage between script verification and this test session.

Concrete reproduction, not executed: collect or stub the single approval test
with live opt-in and dummy credentials. Its fixture graph has no revision or
authentication preflight dependency. A stub client is called even if a separate
smoke test would fail.

Fix: require one fail-closed, session-level preflight for every call fixture.
Require HTTPS, verify expected immutable image/revision and endpoint identity,
bind the intended test database, validate authentication boundaries, and check
required live tooling before any call. Consume an explicit release approval
record for DR-01 through DR-05; missing evidence must block the session.

### F05 The live matrix accepts wrong outcomes and cannot prove one call

Evidence: [approval assertion](tests/e2e/test_live_call.py#L114),
[input replay](tests/e2e/test_live_call.py#L123),
[unanswered alternatives](tests/e2e/test_live_call.py#L243),
[cancellation assertion](tests/e2e/test_live_call.py#L271),
[row count](tests/e2e/test_live_call.py#L289), and
[terminal helper](tests/e2e/test_live_call.py#L95).

Concrete false-positive inputs, not executed:

* Invert approval and rejection: the approval test still accepts either result.
* Return `expired/no_answer` for every input request: replay equality still passes without a spoken answer.
* Ignore client cancellation and expire at the normal deadline: the cancellation test waits up to another 240 seconds and accepts any expired result.
* Map every unanswered call to `disconnected`: the broad expired-outcome set still passes.
* Return correct JSON only after 220 seconds: no elapsed-time assertion enforces the 210-second requirement.
* Create two ACS calls but retain one row and one call ID: JSON equality and the database row count still pass.
* Persist a different terminal outcome from the HTTP response: the common helper checks only existence and request ID, not result equality.

There are no dedicated rejection, answered-content, initial-silence, supported
busy/decline, mid-call-disconnect, forced-deadline, concurrent replay, duplicate
callback, or MCP transport cases. A scalar `call_id` cannot count outbound
attempts: [call attachment](src/ask_my_human/persistence/repository.py#L75)
retains only the first attachment. The 240-second HTTPX timeout is a transport
setting, not an end-to-end deadline assertion or proof of MCP client behavior.

Fix: add scenario-specific expected statuses/outcomes and validate the public
result model, nonblank answer, and complete stored/wire equality. Observe an
accepted pending request before cancelling, then require `cancelled` promptly
and stable terminal state. Measure monotonic elapsed time. Add the missing MCP,
callback, and concurrent-replay scenarios; count actual ACS create attempts from
independent, content-free provider evidence. Treat carrier-unavailable cases as
explicit approved limitations, never successes. Preserve the one-call/no-retry
product contract and do not add production test hooks.

### F06 Required telemetry evidence can be silently skipped or premature

Evidence: [optional import](tests/e2e/test_live_call.py#L178),
[single sentinel query](tests/e2e/test_live_call.py#L194),
[dependency manifest](pyproject.toml#L8), and [uv.lock](uv.lock).

Neither runtime/dev dependencies nor the committed lock include
`azure-monitor-query`. The live test uses `pytest.importorskip`, so a clean locked
environment skips mandatory telemetry validation even with explicit live opt-in.
A run can finish successfully without proving privacy. This is a manifest/lock
fact, not an assumption about extra packages in someone's current environment.

If that optional package is installed manually, the test checks only one prompt
sentinel. It does not seed/assert answer, phone, idempotency, authorization,
callback, or connection-string sentinels. It queries immediately after the call:
the docstring does not implement an ingestion wait. A visible request span does
not prove all later log batches have arrived, so absence can be premature.

Concrete reproduction, not executed: invoke the telemetry test in the frozen
environment with fixture prerequisites stubbed. Missing query SDK produces a
skip rather than a required-evidence failure. Alternatively, return a request-ID
row immediately and a sensitive log in a later batch; the current checks pass
before that batch becomes visible.

Fix: fail closed on unavailable required query tooling. Coordinate any approved
test dependency with the foundation owner; this review changes no dependencies.
Use bounded ingestion polling, successful query-status checks, positive evidence
covering the relevant export interval, and all required sentinel categories.
Keep query results, tokens, and response bodies out of retained test artifacts.

### F07 Publication does not bind the deployed image to reviewed source

Evidence: [image override](scripts/deploy_azure.sh#L65),
[working-directory build](scripts/deploy_azure.sh#L95), and
[deploy sequence](scripts/deploy_azure.sh#L207).

The script tags the build using `git rev-parse HEAD` but uploads the working
directory without a cleanliness check. Modified tracked or included untracked
source can be published under the reviewed commit's tag. A SHA-shaped tag also
does not make an ACR tag immutable.

There is a second deterministic mismatch: `resolve_image` honors an existing
`CONTAINER_IMAGE`, but `build_image` always builds the current Git SHA. During
`deploy`, a stale override can deploy and verify an older image while the newly
built image is unused. A rebuild under the same tag is not distinguished by the
revision's string comparison either.

Concrete reproduction, not executed: use stub Azure/Git commands, set an old
image override, and capture build versus deployment inputs. They differ. With
no override, modify a included source file: the image tag remains the same SHA.

Fix: separate normal deployment from deliberate rollback. Build only a clean,
reviewed source snapshot; reject mismatching overrides in normal deployment.
Resolve the pushed digest and deploy/verify that digest, or enforce equivalent
registry tag immutability plus provenance. Rollback should accept an explicitly
approved previous digest without building unrelated source.

### F09 Compose rejects normal local MCP requests

Evidence: [published application port](compose.yaml#L24),
[host allowlist](compose.yaml#L36), and
[transport security wiring](src/ask_my_human/main.py#L167).

Compose publishes port 8000 but allows only the literal host `localhost`.
Normal requests to `http://localhost:8000/mcp` carry `Host: localhost:8000`.
The installed MCP validator uses exact host matching unless the allowed value
ends in `:*`; it does not discard the port. It therefore returns 421 before
MCP request handling. Requests to `127.0.0.1:8000` are also not allowed.

Concrete reproduction, not executed: validate a request with that Host header
and JSON content type using the installed transport-security middleware and the
Compose settings. No credentials or phone call are needed.

Fix: include the intended explicit local host/port pairs, retaining DNS-rebinding
protection. If a local browser client is supported, account for its HTTP Origin
separately: the current application derives HTTPS-only origins. Add a call-free
MCP initialization or tools-list smoke check with the real local Host header.

## Major Findings

### F08 Python base images are not pinned to the reviewed digest

Evidence: [builder base](Dockerfile#L2) and [runtime base](Dockerfile#L25).

Both stages use mutable `python:3.12-slim-bookworm` tags. The explicit reviewed
digest requirement is unmet; identical source and lockfile do not identify the
same OS/interpreter image on a later build. uv's version pin is correctly present
and is not conflated with this defect.

Fix: pin both stages to the reviewed compatible Python digest and record its
controlled update process. The missing digest is directly checkable from the
two FROM instructions; no registry access is required to establish the gap.

### F10 Local-only Compose publishes database and trusted-header API widely

Evidence: [database port](compose.yaml#L9), [application port](compose.yaml#L23),
[public local credential](compose.yaml#L7), and
[trusted-principal handling](src/ask_my_human/main.py#L175).

The bindings omit a host address, so Docker publishes on all host interfaces by
default. Any reachable client can use the declared database credentials; the
app also has no Container Apps authentication proxy in Compose and interprets
the platform principal header directly. Placeholder endpoints are not themselves
working Azure credentials, so this does not prove an outsider can place a real
call in the supplied configuration. It does expose local data and a trusted-only
development API when host networking permits access.

Fix: bind both ports to loopback, or remove database publishing when unnecessary.
Keep Compose explicitly development-only and do not add local secret forwarding
to it. Confirm resolved host bindings and reject externally supplied principal
headers in any environment not behind the trusted ingress contract.

### F11 What-if is discarded and deployment requires no review approval

Evidence: [suppressed what-if](scripts/deploy_azure.sh#L85),
[required environment names](scripts/deploy_azure.sh#L13), and
[default deploy command](scripts/deploy_azure.sh#L199).

`run_what_if` discards the change list and immediately proceeds to publish/deploy.
Its instruction to rerun without `--no-pretty-print` does not remove the separate
stdout redirection. Required variable presence does not establish retention
approval, number eligibility, target-client qualification, or reviewed what-if
acceptance. Calling the script without a subcommand defaults to mutation.

Concrete reproduction, not executed: a stub what-if emits an unexpected resource
deletion but exits zero. The deployment branch suppresses that output and
continues. No condition checks DR approval or change-list acceptance.

Fix: make a non-mutating usage/help command the default; require explicit deploy.
Produce a sanitized reviewable what-if result and require recorded approval tied
to the source/image/parameter set before mutation. Keep secure values redacted.
DR decisions remain external, but enforcing their presence is code-fixable.

### F12 Revision verification omits health and bounded probe handling

Evidence: [revision lookup](scripts/deploy_azure.sh#L143),
[running-state check](scripts/deploy_azure.sh#L155), and
[unbounded curl calls](scripts/deploy_azure.sh#L170).

Verification queries `latestReadyRevisionName`, image, active state, and running
state, but never `healthState`, readiness-probe success, or whether the intended
new revision has become ready. A stale previously ready revision can be selected;
the image check detects a different image string but not a changed revision
reusing that string. `verify` can omit the expected image altogether. Curl has
no connect or overall deadline, so a nonresponsive endpoint can hang the gate.

Concrete reproduction, not executed: provide metadata showing `Running` and
active with an unhealthy state; the script never requests the health field.
Stub curl to block: there is no script-level timeout for that probe.

Fix: distinguish diagnostic inspection from release verification. Release mode
must require expected digest/revision, poll readiness and healthy/running state
with a bounded deadline, and apply curl connect/overall limits. On failure,
produce sanitized diagnostics and an explicit rollback or blocked-release
outcome. `set -e` stops this script but does not provide the planned recovery
record or prevent an independently invoked harness from running.

### F13 Retention test races normal maintenance and leaves a test row

Evidence: [row inserts and delete-count assertion](tests/e2e/test_live_call.py#L137),
[retained-row assertion](tests/e2e/test_live_call.py#L145),
[normal purge loop](src/ask_my_human/application/maintenance.py#L39), and
[global terminal purge](src/ask_my_human/persistence/repository.py#L143).

The test correctly invokes the production purge path and checks both expired
and fresh rows. However, the deployed hourly maintenance loop can delete its
backdated row between insertion and `purge_once`. In an otherwise empty test
database, the explicit invocation then returns zero and the test fails despite
correct retention. There is also no `finally` cleanup: the fresh synthetic row
remains until normal retention, and failures can leave both rows.

Concrete reproduction, not executed: insert the backdated fixture, allow the
normal purge to run, then resume the test. The row is correctly gone but the
`>= 1` assertion fails.

Fix: coordinate this proof in an isolated test database/transaction so the test's
normal purge invocation is attributable, without disabling production maintenance
or adding production hooks. Always clean up both controlled IDs in `finally`.
Retain the fresh-row control and use the approved retention setting. The normal
purge intentionally deletes all eligible terminal rows, so an operator must
explicitly approve the database target.

## Minor Findings

### F14 Phase 3 source is absent from the changes log

Evidence: [declared implemented scope](.copilot-tracking/changes/2026-09-15/ask-my-human-tight-mvp-changes.md#L9),
[stale integration summary](.copilot-tracking/changes/2026-09-15/ask-my-human-tight-mvp-changes.md#L168),
and [unchecked Phase 3](.copilot-tracking/plans/2026-09-15/ask-my-human-tight-mvp-plan.instructions.md#L201).

All six reviewed files are tracked, but C contains no Step 3.1, 3.2, or 3.3
implementation or validation entries. It also says Phase 2 is intentionally
unimplemented although the composition exists. This is an evidence/traceability
gap, not a reason to pretend the image, CI, or harness is absent. Unchecked
completion boxes remain appropriate while required checks and defects are open.

Fix: after owner verification, record the actual implemented files, scoped
results, unresolved defects, and external gates. Update checkboxes only when
their acceptance criteria are met. This review intentionally does not edit C,
P, D, R, or L.

## Coverage and Release Prerequisites

All three Phase 3 plan items and their detailed acceptance criteria were compared
with C and verified source. Step 3.1 is partial, Step 3.2 has the required command
inventory but no execution evidence from this session, and Step 3.3 is partial
with material false-positive and missing-scenario coverage. A percentage would
hide the difference between missing code and intentionally unrun release gates.

All F01 through F14 are code-, test-, or documentation-fixable. F01 needs the
migration owner; F02 needs the release/observability owners; most remaining
changes belong to the release owner. Any query dependency addition must return
to the foundation owner. No finding requires adding a worker, retry, new channel,
second image, or production test hook.

External prerequisites cannot be resolved from repository inspection:

| Gate  | External evidence required                              | Relationship to code fixes             |
|-------|---------------------------------------------------------|----------------------------------------|
| DR-01 | Eligible numbered ACS resource, owner consent, region    | Supplies real call target and support  |
| DR-02 | Entra tenant, registrations, role, authorized identities | Supplies auth inputs; does not fix F03 |
| DR-03 | Approval of 24h request and 30d telemetry retention       | Approves policy and test DB access     |
| DR-04 | Subscription, region, registry, deploy/build permissions | Enables approved deployment            |
| DR-05 | Target MCP client timeout and cancellation qualification | Needs missing MCP harness coverage     |

Also required later: reviewed what-if acceptance, immutable-image provenance,
healthy revision/probe/auth evidence, authorized test-database and telemetry
query access, provider call-count evidence, and carrier-specific outcome
availability. No supplied artifact demonstrates these approvals or live results.
Their absence does not excuse the code defects above.

## Validation Performed

* Read all five supplied requirements artifacts and all six requested implementation files in full.
* Matched every Phase 3 item to C; verified the unlogged implementation files with scoped `git ls-files`.
* Read the narrow dependency paths and installed library behavior supporting the findings.
* `docker compose config --quiet` passed, confirmed by the distinct `PHASE3_COMPOSE_PARSE_OK` marker.
* `bash -n scripts/deploy_azure.sh` passed, confirmed by `PHASE3_DEPLOY_SHELL_PARSE_OK`; the script was not executed.
* Checked only this report for editor diagnostics and whitespace after editing.

An earlier terminal response contained unrelated pytest output; it was not
credited as review evidence. Parser checks were repeated with distinct completion
markers. No pytest run, live collection, Docker build/start, Azure command, network
request, deployment, call, publish, commit, dependency change, or full-repository
check was performed by this review. Reproduction recipes above remain unexecuted
and are explicitly marked as such. Runtime and CI results belong to the parent.

## Recommended Next Validations

* [ ] Parent: add and run an offline percent-encoded DSN regression, asserting no secret appears in startup errors.
* [ ] Parent: capture image/server logs for query, body, and exception sentinels without placing calls.
* [ ] Parent: exercise Compose health and MCP initialization with real local Host headers and confirm loopback-only bindings.
* [ ] Parent: use stubbed Azure/curl/Git commands to test protected health routes, unhealthy/stale revisions, image overrides, dirty builds, what-if rejection, and timeout handling.
* [ ] Parent: prove call fixtures cannot execute when release preflight, required tooling, HTTPS, or target binding fails.
* [ ] Parent: mutate expected outcomes, cancellation handling, response timing, DB results, and ACS attempt counts to ensure the harness rejects each false-positive case.
* [ ] Parent: exercise retention with competing maintenance and failure cleanup in an isolated PostgreSQL database.
* [ ] Parent: run default live collection/skip checks, scoped Ruff/mypy, then the full repository/coverage/image/Bicep gates it owns.
* [ ] Release owner: after code fixes and documented DR approvals, review what-if and verify immutable revision, probes, and auth before separately authorized live execution.
* [ ] Release owner: execute the complete HTTP/MCP outcome, race, cancellation, call-count, telemetry-ingestion, and retention matrix; record approved carrier limitations explicitly.

## Clarifying Questions

No additional input is needed to resolve the source-level findings. Before release:

* Who approves DR-01 through DR-05 and binds that approval to the target image, endpoint, and test database?
* Which MCP client and carrier capabilities define the authorized live matrix and acceptable documented limitations?
* Which existing telemetry-query mechanism and identity should the foundation owner approve for mandatory privacy validation?