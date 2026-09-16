---
title: Phase 2 Composition and Infrastructure Validation
description: Read-only validation of the tight MVP Phase 2 implementation and composition boundaries.
ms.date: 2026-09-16
---

## Validation Scope

Status: Failed. Phase 2 validation is finalized; the requested filename uses
ordinal 003. Both integration steps have implementation, but required composed
behavior fails. This is not a claim that deployment or live calls were tested.

Only this report was edited. Product files, tests, plans, research, dependencies,
and existing user changes were preserved. No environment file or secret was read;
no Azure operation, live call, dependency synchronization, or commit ran.
Phase 1A internals and Phase 1B module internals remain with their validators;
overlap below is limited to integration-specific facts.

Inputs read in full:

* [Implementation plan](.copilot-tracking/plans/2026-09-15/ask-my-human-tight-mvp-plan.instructions.md#L183)
* [Planning log](.copilot-tracking/plans/logs/2026-09-15/ask-my-human-tight-mvp-log.md#L1)
* [Changes log](.copilot-tracking/changes/2026-09-15/ask-my-human-tight-mvp-changes.md#L1)
* [Primary research](.copilot-tracking/research/2026-09-15/tight-mvp-scope-research.md#L1)
* [Implementation details](.copilot-tracking/details/2026-09-15/ask-my-human-tight-mvp-details.md#L733)

## Phase Requirements and Changes Log Comparison

Steps 2.1 and 2.2 remain unchecked. The current
[resumption entry](.copilot-tracking/changes/2026-09-15/ask-my-human-tight-mvp-changes.md#L170)
acknowledges existing Phase 2 composition, but does not itemize completion or
record its scoped gates. The earlier report's claim that the log described
composition as unimplemented is superseded. Unchecked boxes are not missing code.

| Item | Requirement and verified evidence | Assessment |
| --- | --- | --- |
| 2.1 construction | Settings, telemetry, credentials, ACS client, pool, repository, service, maintenance, and validator are created once in [build_components](src/ask_my_human/main.py#L113). HTTP and MCP receive the same use case. | Present; telemetry attachment has a gap (F5). |
| 2.1 routing | MCP app is built before session-manager entry, HTTP routes are registered first, and MCP is mounted last at [main.py](src/ask_my_human/main.py#L165). | Present; authorized tool invocation and technical callbacks fail (F1, F2). |
| 2.1 startup | [Lifespan](src/ask_my_human/main.py#L182) awaits [pool open and wait](src/ask_my_human/persistence/pool.py#L24) before serving. | Normal startup present; cancellation cleanup incomplete (F6). |
| 2.1 shutdown | Exit stack stops maintenance, exits MCP, closes pool, and runs all client closers. [ASGI tests](tests/integration/test_asgi_app.py#L192) exercise normal cleanup and client-close failure. | Normal paths covered; task supervision and failure-path draining incomplete (F4, F6). |
| 2.1 validation | Existing nine ASGI tests exercise requests, callbacks, health, metadata, MCP initialization, and maintenance. | Preserved pass result; no successful mounted tools/call or real component-factory telemetry coverage. Fresh mypy and Ruff not run. |
| 2.2 module graph | [Resource-group root](infra/main.bicep#L1) instantiates identity, observability, PostgreSQL, communications, and Container App. Output references establish upstream dependencies. | Structurally present; existing ARM artifact confirms dependency graph, not fresh compilation. |
| 2.2 bindings | [Development bindings](infra/environments/dev.bicepparam#L1) match all 14 root parameters through environment-variable names. Secure password, phone, and Entra-secret inputs retain secure declarations. | Present; callback audience contract is incorrect (F3). |
| 2.2 defaults and outputs | Root forwards 210/205 seconds, 500 milliseconds, 24 hours, and 30 days. Its four public outputs are location, app name, app resource ID, and FQDN. | Present; no root secret output or committed parameter value found. Nested module security remains Phase 1B-owned. |
| 2.2 runtime shape and build | Existing [ARM artifact](infra/main.json#L1) contains one app, one container/image, and no worker, job, queue, cache, or sidecar resource. | Static shape passes; fresh Bicep build unavailable. |

## Critical Findings

### F1: Authorized HTTP Identity Cannot Invoke the Mounted MCP Tool

Evidence: [main.py](src/ask_my_human/main.py#L165) constructs MCP without an
authentication bridge; the trusted principal parser is injected only into HTTP
at [main.py](src/ask_my_human/main.py#L209). The MCP adapter requires SDK token
context at [server.py](src/ask_my_human/mcp_adapter/server.py#L189).
The preserved no-network repro sends the same authorized identity through both
transports: HTTP returns 200 and dispatches once, while MCP tools/call returns
`unauthenticated` and does not dispatch. The existing
[MCP composition test](tests/integration/test_asgi_app.py#L272) only initializes
a session, so its pass does not establish usable tool authentication.

Minimal fix: share the trusted platform-principal authorization boundary with
MCP, preserving subject identity, role enforcement, and the configured client
allowlist. Do not trust arbitrary identity headers outside platform auth.
Local check: initialize a mounted session and invoke tools/call with authorized,
missing, wrong-role, and non-allowlisted identities; compare HTTP/MCP principal
and dispatch results. Adapter-internal bypass findings remain Phase 1A-owned.

### F2: Composition Acknowledges Technical Call Failures Without Dispatch

Evidence: [parse_callback_events](src/ask_my_human/main.py#L102) retains only
`call_event`, losing the parser's
[dependency_failure classification](src/ask_my_human/telephony/events.py#L38).
The [callback route](src/ask_my_human/api/callbacks.py#L65) returns 200 for the
resulting empty sequence. Preserved repro: CreateCallFailed with numeric code
500 has `dependency_failure=True`, produces zero domain events, and is
acknowledged without use-case dispatch. The pending request therefore does not
receive the required durable technical-error completion from that callback.

Minimal fix: preserve technical classification and request correlation through
an agreed typed use-case dispatch path, then persist a sanitized execution error
with first-terminal semantics. Route any port change through the foundation
owner; do not add repository access to the HTTP adapter.
Local check: feed a signed, locally mocked technical failure through the mounted
callback route and assert one durable dependency error, stable replay, and a
no-op duplicate. CallConnected is also discarded by the composition test at
[test_asgi_app.py](tests/integration/test_asgi_app.py#L323); recognition timing
itself is already a Phase 1A finding and is not re-reviewed here.

### F3: Callback Endpoint and JWT Audience Share an Incompatible Setting

Evidence: [infra/main.bicep](infra/main.bicep#L31) describes the audience as the
public service URL, and [dev.bicepparam](infra/environments/dev.bicepparam#L15)
forwards that input. [Settings](src/ask_my_human/config.py#L24) requires an HTTP
URL; the [gateway factory](src/ask_my_human/telephony/acs_client.py#L47) appends
the callback route to it. The same value is passed to the JWT validator at
[main.py](src/ask_my_human/main.py#L143), which performs exact audience validation
at [acs_callback.py](src/ask_my_human/security/acs_callback.py#L82).
This contradicts the required ACS resource audience in
[primary research](.copilot-tracking/research/2026-09-15/tight-mvp-scope-research.md#L214).

Minimal fix: separate the public callback endpoint/base URL from the ACS resource
audience, align settings and Bicep bindings, and pass each only to its consumer.
Use the documented ACS token audience identifier, not a guessed service URL or
an assumed interchangeable ARM identifier. This requires coordinated foundation,
telephony, and integration edits. Do not disable audience validation.
Local check: mocked OpenID/JWKS and a locally signed resource-audience JWT must
pass the composed validator while a service-URL audience fails; separately
assert the create-call callback URL. This is source-verified against the contract,
not a live ACS-token observation.

### F4: Failed Maintenance Remains Invisible to Runtime Supervision

Evidence: [lifespan](src/ask_my_human/main.py#L191) launches detached asyncio
tasks, then yields without monitoring their completion. Exceptions escape the
[maintenance loop](src/ask_my_human/application/maintenance.py#L46), while
[readiness](src/ask_my_human/api/health.py#L29) checks only settings and pool state.
Preserved repro: expiry failure leaves both health endpoints returning 200 and
surfaces an exception group only during shutdown. Required stale expiry stops;
the same composition pattern cannot detect a stopped retention loop.
Healthy process liveness alone is not a defect; continued readiness without
working required maintenance is the integration failure.

Minimal fix: supervise both tasks within the lifespan and select an explicit
failure policy, such as failing the lifespan/process or marking readiness
unavailable with controlled recovery. At shutdown, cancel and drain every task
before raising aggregated errors: [sequential task awaits](src/ask_my_human/main.py#L234)
currently stop at the first non-cancellation exception.
Local check: inject expiry and purge failures separately, assert the selected
failure policy, and verify both tasks finish before pool/client closure.

## Major Findings

### F5: Normal Startup Does Not Attach FastAPI Instrumentation

Evidence: [main.py](src/ask_my_human/main.py#L15) binds `FastAPI` before calling
[configure_observability](src/ask_my_human/main.py#L115), then constructs the app
using that original binding at [main.py](src/ask_my_human/main.py#L198).
Installed FastAPI instrumentation replaces the module's `fastapi.FastAPI`
attribute, rather than changing the already imported class. There is no explicit
`instrument_app` call on the returned app. The
[observability setup test](tests/unit/test_observability.py#L194) replaces Azure
Monitor setup with an option recorder, so it cannot catch this attachment gap.

Installed-source evidence: OpenTelemetry FastAPI `__init__.py`, lines 442 and
465; Azure Monitor `_configure.py`, line 389. These are dependency-source reads,
not a newly executed telemetry repro. This finding applies to normal direct
startup without earlier external auto-instrumentation. Manual application
telemetry can still exist; the finding is not that all telemetry is absent.

Minimal fix: explicitly instrument the composed app once after construction,
with content-free instrumentation settings and no sensitive header/body capture.
Local check: exercise an ASGI request with in-memory exporters, prove an attached
server span and correlation, and assert sensitive sentinels remain absent.
Missing internal operation metrics and exception-log leaks remain Phase 1A-owned.

### F6: Startup Cancellation Can Bypass Pool Cleanup

Evidence: [main.py](src/ask_my_human/main.py#L187) registers pool cleanup only
after `open()` finishes. The [pool wrapper](src/ask_my_human/persistence/pool.py#L24)
starts workers and then waits for readiness. Installed Psycopg source opens
workers before waiting and has no cancellation-finally cleanup around that wait.
Cancellation at this boundary can therefore unwind client cleanup without
closing the partially opened pool.

The earlier fake-pool observation is preserved: a fake that partially opens and
then raises is not closed. It does not prove that a normal real connection
timeout leaks. Installed Psycopg `pool_async.py`, line 217, explicitly closes
the pool before raising PoolTimeout; that broader candidate is withdrawn.
Cancellation evidence is source-based, not a new real-driver runtime repro.

Minimal fix: register idempotent pool cleanup before awaiting open, or make the
pool's open operation exception- and cancellation-safe. Keep this in the owning
lifecycle abstraction. Local check: cancel startup after workers begin but before
readiness; verify pool/client closure and no surviving workers. Retain separate
normal-timeout and successful-startup tests.

## Minor Finding

### F7: Phase 2 Completion Evidence Is Not Reconciled

The [plan checklist](.copilot-tracking/plans/2026-09-15/ask-my-human-tight-mvp-plan.instructions.md#L190)
is unchecked and the [changes log](.copilot-tracking/changes/2026-09-15/ask-my-human-tight-mvp-changes.md#L170)
acknowledges composition without step-specific changes or verification results.
The owned source/test files and deployment root exist, including the generated
ARM artifact not itemized as a Phase 2 change.

Minimal fix: after corrections and checks, the owners should record actual
Phase 2 files, outcomes, deviations, and remaining gates. Do not mark either
step complete merely because its files exist. No plan or changes-log edit was
made during validation.

## Coverage and Evidence

All Step 2.1 and 2.2 requirements were compared with the log and actual files.
Step 2.1 is partially implemented and functionally failing; Step 2.2 has verified
static composition but an incompatible runtime audience contract and no fresh
compiler gate. No whole missing phase or second service instance was found.

Preserved prior evidence, not rerun or relabeled as newly reproduced:

* Scoped tests: 37 passed in 2.15 seconds, including all nine ASGI tests. Selection
  covered composition, callback routing, agent and callback security, maintenance,
  and observability. Product/test files were not changed.
* Network-free ASGI repros established the HTTP/MCP dispatch mismatch, dropped
  technical callbacks, and unsupervised maintenance failure described above.
* MCP transport rejected hostile Host with HTTP 421 and hostile Origin with HTTP
  403. Host/origin protection is present and distinct from principal authorization.
* The partial-open fake-pool repro remains evidence of registration order, subject
  to the real-driver timeout correction in F6.

Completed on resumption:

* Read-only tracing resolved lifespan registration/draining, real pool timeout
  cleanup, telemetry attachment, and endpoint/audience wiring.
* Node parsed the existing ARM JSON and checked all 14 root/development parameter
  names match. The artifact contains one Container App with one container and
  no excluded runtime resource. Communications depends on identity; Container App
  depends on communications, identity, observability, and PostgreSQL.
* The source root's five module instances, secure input forwarding, timing and
  retention defaults, and four non-secret public outputs were verified. Existing
  ARM JSON is supporting evidence only; source/artifact freshness is unproven.

Limits: no new Python test, repro, mypy, or Ruff execution was performed. Required
Python environment/discovery tools could not be loaded in this session. Neither
Azure CLI nor standalone Bicep was available on PATH or in the checked local
locations, so no fresh compilation is claimed. No tool installation was attempted.
Tenant-owned DR-01 through DR-05, live behavior, and module-internal findings are
outside this validation. Report validation passed: no editor diagnostics, all 41
file links and line-anchor bounds valid, and whitespace, frontmatter boundary,
and final-newline checks passed. These are report checks, not product gates.

## Recommended Next Validations

* [ ] Add mounted HTTP/MCP identity parity and authorization regression checks (F1).
* [ ] Exercise technical callbacks through the composed service and durable replay (F2).
* [ ] Validate separate callback URL and ACS audience using local JWT/JWKS fixtures (F3).
* [ ] Test expiry/purge failure supervision, complete task draining, and cancelled pool startup (F4, F6).
* [ ] Verify actual ASGI span attachment, correlation, and sensitive-sentinel exclusion with in-memory exporters (F5).
* [ ] Rerun the preserved 37-test selection, the Phase 2 ASGI suite, scoped mypy, and scoped Ruff after fixes.
* [ ] With an existing compiler available, run `bicep build infra/main.bicep --stdout` or `az bicep build --file infra/main.bicep --stdout`; compare the fresh graph and check bindings without reading secrets.
* [ ] Reconcile Phase 2 log/checklist evidence and cross-owner Phase 1A/1B blockers before release validation.

## Clarifying Questions

None blocks these findings. No secret values, tenant identifiers, or new scope
decisions are required to implement the local fixes. DR-01 through DR-05 remain
separate deployment/release acceptance gates, not requests to supply secrets here.
