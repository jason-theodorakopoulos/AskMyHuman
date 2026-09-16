<!-- markdownlint-disable-file -->
# Ask My Human Cross-Phase Quality Audit

## Metadata And Result

* Date: 2026-09-16
* Original audit status: Needs Rework; all five findings corrected in the parent follow-up below
* Remaining local findings after correction: 0 critical, 0 major, 0 minor
* Original discovered follow-up items: 5, all resolved locally
* Scope: Independent read-only source audit of coordinated lifecycle, persistence,
  callback, telemetry, deployment, and live-harness repairs
* Implementation changes: None; only this review artifact was created

Related artifacts:

* [Implementation plan](.copilot-tracking/plans/2026-09-15/ask-my-human-tight-mvp-plan.instructions.md)
* [Changes log](.copilot-tracking/changes/2026-09-15/ask-my-human-tight-mvp-changes.md)
* [Primary research](.copilot-tracking/research/2026-09-15/tight-mvp-scope-research.md)
* [Phase 1A validation](.copilot-tracking/reviews/rpi/2026-09-16/ask-my-human-tight-mvp-plan-001-validation.md)
* [Phase 1B validation](.copilot-tracking/reviews/rpi/2026-09-16/ask-my-human-tight-mvp-plan-002-validation.md)
* [Composition validation](.copilot-tracking/reviews/rpi/2026-09-16/ask-my-human-tight-mvp-plan-003-validation.md)
* [Release validation](.copilot-tracking/reviews/rpi/2026-09-16/ask-my-human-tight-mvp-plan-004-validation.md)
* [Documentation validation](.copilot-tracking/reviews/rpi/2026-09-16/ask-my-human-tight-mvp-plan-005-validation.md)
* [Owned-scope quality review](.copilot-tracking/reviews/quality/2026-09-16/ask-my-human-tight-mvp-quality.md)

The existing plan and planning-log edits were treated as user-owned context, not
review changes. Prior validator results were reused as historical evidence, not
rerun or presented as validation of the current source. No new parallel validator
runs are claimed: subagent and deferred-tool loading capabilities were unavailable.

## Remaining Findings

### C1 Critical: Late Call Connection After Expiry Receives No Cleanup

Evidence: [terminal callback return](src/ask_my_human/application/service.py#L275),
[create response correlation](src/ask_my_human/application/service.py#L368),
[expiry cleanup](src/ask_my_human/application/service.py#L248), and
[maintenance selection](src/ask_my_human/persistence/repository.py#L201).
The [lifecycle requirement](.copilot-tracking/details/2026-09-15/ask-my-human-tight-mvp-details.md#L294)
requires creator cancellation to expire and hang up the shared call.

If cancellation or the work cutoff interrupts an in-flight create before its
response supplies a call ID, expiry can successfully persist a terminal row with
no call ID and perform no hang-up. When ACS subsequently delivers a correlated
CallConnected, the terminal-state return discards it before attaching or cleaning
up the newly known call. Maintenance selects only pending rows, so it cannot
recover this terminal row either. The service can leave the old call active while
admitting a different request. This is a missing cleanup path, not a claim that a
second ACS call or a specific carrier outcome was observed.

Discriminating check, not executed: use a gateway whose create method records
submission and waits without returning an ID. Cancel the creator, verify the
durable cancelled result, then deliver CallConnected with that request ID and a
synthetic call ID. Require one bounded hang-up, no recognition, and the unchanged
terminal result. The current terminal-state return cannot make that hang-up.
Repeat with deadline expiry to cover the shared branch.

Minimal fix: handle late connected events for cancelled, expired, or failed rows
as bounded cleanup-only events, retaining authentication and any already-known
call-ID mismatch rejection. Use the newly available callback call ID when no ID
was stored. Do not reopen the row, start recognition, or interrupt a responded
row's acknowledgement. Coordinate service and telephony ownership.

### M1 Major: Losing Expiry Interrupts Winning Response Acknowledgement

Evidence: [ignored expiry update result](src/ask_my_human/application/service.py#L234),
[unconditional hang-up](src/ask_my_human/application/service.py#L247), and
[acknowledgement after winning completion](src/ask_my_human/application/service.py#L321).

A success callback can win the terminal update and begin acknowledgement while
the initiating waiter is still polling. If cancellation or its timeout then
selects expiry before that waiter observes the success, `_expire` loses its
conditional update, reloads the responded row, and unconditionally hangs up.
The returned result remains correct, but acknowledgement playback is interrupted.
The analogous late-create-response path already avoids hanging up a matching
responded call; expiry does not preserve that protection.

Discriminating check, not executed: block the polling read, let an approval
callback persist success and enter a gateway acknowledgement barrier, then
cancel the creator signal. Assert the approved result remains authoritative and
no separate hang-up occurs before playback completion or its existing timeout.
An even smaller check calls `_expire` with a stale pending snapshot after the
repository has become responded and asserts no premature gateway hang-up.

Minimal fix: retain the conditional-update outcome and respect the authoritative
terminal state when choosing cleanup. A losing expiry must not preempt the
responded callback's bounded acknowledgement/hang-up owner. Preserve cleanup for
actual expiry and failed cleanup reads, and add the focused race regression.

### M2 Major: Live Preflight Requires The Wrong HTTP Validation Status

Evidence: [authorized preflight assertion](tests/e2e/test_live_call.py#L329),
[HTTP error mapping](src/ask_my_human/api/requests.py#L20), and
[manual validation handling](src/ask_my_human/api/requests.py#L92).

Preflight posts an authenticated empty object to `/v1/requests` and requires 422.
The actual router validates manually, catches the Pydantic validation error, and
returns the defined 400 `invalid_request` response. Consequently, a correctly
authenticated healthy deployment fails the session preflight and cannot execute
the live matrix. The harness unit mock returns the incorrect 422, so it reproduces
the assumption instead of checking the adapter contract.

Discriminating check, not executed: post `{}` through the existing ASGI request
router with its fake authenticator and assert 400, `invalid_request`, and zero
use-case calls; feed that response through the preflight assertion. The existing
[HTTP mapping test](tests/unit/api/test_requests.py#L77) already encodes 400.

Minimal fix: require the existing 400 error contract, including its stable error
code, and replace the isolated 422 stub with a regression grounded in the actual
router. Do not weaken the negative authentication checks or send a valid paid
request to satisfy preflight.

### M3 Major: Live Result Checks Reject Valid Omitted Null Answers

Evidence: [HTTP serialization](src/ask_my_human/api/requests.py#L90),
[wire comparison](tests/e2e/test_live_call.py#L363),
[storage comparison](tests/e2e/test_live_call.py#L453), and
[MCP serialization](src/ask_my_human/mcp_adapter/server.py#L172).

HTTP intentionally omits `answer` when it is null. The harness parses that valid
body, then compares it to a default model dump that adds `answer: null`. Approval,
rejection, and all expired HTTP outcomes therefore fail canonical equality.
The later storage-to-wire comparison repeats the mismatch. MCP includes nulls,
so changing every comparison to exclude nulls would break the other transport.
The [existing HTTP regression](tests/unit/api/test_requests.py#L44) explicitly
expects the valid three-field expired body; harness fixtures instead include
`answer: null` in all synthetic bodies.

Discriminating check, not executed: pass the existing HTTP regression's
three-field `expired/no_answer` body to `_validate_terminal_wire` with the matching
outcome. It adds the missing null and fails equality. Cover both omitted and
explicit null across HTTP and MCP, plus a nonblank input answer and extra-field
rejection.

Minimal fix: validate against the existing public model and compare normalized
models or use explicitly transport-aware serialization in both checks. Preserve
exact status, outcome, nonblank answer, request ID, and extra-field validation;
do not change the public response contract to accommodate the harness.

### M4 Major: Verifier Output Cannot Be Consumed By Live Evidence Gate

Evidence: [verification JSON output](scripts/deploy_azure.sh#L282),
[strict evidence policy](tests/e2e/test_live_call.py#L54),
[deployment evidence model](tests/e2e/test_live_call.py#L76), and
[live evidence parsing](tests/e2e/test_live_call.py#L235).
The [live dependency](.copilot-tracking/details/2026-09-15/ask-my-human-tight-mvp-details.md#L1048)
requires the previously verified immutable revision.

The verifier emits `source_sha`, `authentication_verified`, and
`paid_calls_authorized`, which `_Deployment` forbids as extra fields. It does not
emit `database_sha256`, which that model requires. Even a fresh successful verify
record cannot be passed directly into `LIVE_DEPLOYMENT_EVIDENCE_JSON`; adding the
database fingerprint alone still fails. Both halves' unit tests use independently
constructed records and do not exercise this producer-consumer boundary. No
explicit conversion contract bridges these formats in the reviewed path.

Discriminating check, not executed: take the JSON produced by the existing stubbed
deployment verification test and validate it with `_Deployment.model_validate_json`.
Assert that valid verifier evidence plus the required approved database attestation
passes, while wrong digest, revision, database, stale evidence, and missing
authentication proof fail. No Azure access is needed.

Minimal fix: establish one versioned handoff schema, or an explicit tested
conversion that preserves verified provenance and requires the separate approved
database/isolation attestation. Keep the absence of paid-call authorization
distinct from operator consent. Do not merely ignore all unknown fields or
invent database verification evidence.

## Closure Assessment

| Area | Current source assessment |
| --- | --- |
| Service deadline and single creation | Outer request timeout, remaining work budget, cooperative task cancellation, creator-only create, and bounded cleanup are present. Existing focused tests cover stalled create, admission, polling, recognition, and cleanup. C1 and M1 leave cleanup race closure incomplete. |
| Callback lifecycle | Connected/technical/playback events retain call correlation; durable recognition claim and post-claim state/cutoff checks are present. Terminal playback forwarding is present. No separate new mapping defect was established. |
| Persistence and migration | Responded updates include kind checks, database expiry, wall-clock checks, and the service cutoff. Recognition uses the new migration. Expiry returns rows for cleanup; maintenance recovers after transient failures. No additional source-confirmed database defect was established. |
| Telemetry | Actual awaited operations are enclosed by spans; pending reconciliation and dependency reporting are wired. HTTP middleware restricts exported attributes and disables exception capture. No additional content leak was established in this pass; exporter ingestion was not tested. |
| Deployment | Explicit actions, external approvals bound to source/parameters/what-if, digest identity, current/ready/healthy revision, traffic, and authenticated health checks are present. M4 leaves the live-evidence handoff inconsistent. |
| Live harness | Explicit opt-in, scenario approval, independent provider evidence, telemetry prerequisites, exact outcomes, and MCP cases exist. M2 and M3 reject correct service behavior; M4 prevents direct verifier handoff. |

SDK retry behavior alone was not classified as a duplicate-call bug. Installed
ACS generated request construction supplies repeatability headers. This is not
a claim that provider behavior or physical call uniqueness was exercised.
No fresh exhaustive authentication review or planning-artifact review was performed.

## Validation Evidence And Limits

| Check | Status | Evidence |
| --- | --- | --- |
| Current source and neighboring regression inspection | Complete | Five concrete control-flow or producer-consumer mismatches above; checks are proposed, not falsely reported as executed. |
| New Python repros, pytest, Ruff, mypy, or database checks | Not run | Required deferred-tool loading/Python setup capabilities were unavailable. No interpreter was reconfigured and no packages were installed. |
| Parent complete static gates | Reported by parent | Ruff format/check, mypy, lock freshness, and schema checks passed; not independently rerun here. |
| Parent non-live tests | Reported by parent | Initial 343 passed and two failed; stale migration and one-second fixture failures were fixed, followed by two focused passes. No fresh full-suite result is inferred. |
| Parent image smoke | Reported by parent | Smoke passed after migration-head, shared database namespace, and SDK input-schema corrections; not rerun here. |
| Report diagnostics and local references | Pass | Editor reported no errors. Node validation passed for 31 local references and line anchors, required header, whitespace, and final newline after correcting the initially missing newline. |

No environment or secret file was read. No Azure command, deployment, paid call,
network test, commit, branch, dependency install, or product-file edit was made.
Runtime race schedules above are specified discriminating checks, not newly
executed reproductions. External release acceptance is outside this audit and
is not counted as a code defect.

## Follow-Up Work

### Discovered During Review

1. Core/telephony owner: repair late-terminal connected cleanup and add C1's
   cancellation/deadline regression.
2. Core/telephony owner: preserve winning acknowledgement ownership in M1's race.
3. Release-test owner: align preflight with the HTTP 400 contract and test the
   actual adapter boundary.
4. Release-test owner: normalize optional null answers across HTTP/MCP and storage.
5. Release/deployment owners: align and test the verifier-to-live evidence schema.

### Deferred From Scope

The parent retains ownership of combined final-state validation and existing
release approvals. This pass adds no request for paid external checks and does
not reclassify already documented external gates as implementation findings.
Preserve existing planning and implementation edits. The original findings above
remain a pre-fix evidence snapshot; the following parent resolution supersedes
their open status.

## Parent Resolution: 2026-09-16

* C1 and M1: Added cancellation/deadline late-connection and losing-expiry tests.
   All three first failed, then passed after bounded cleanup-only terminal handling
   and preservation of the winning response's acknowledgement. The full service
   suite passed all 43 tests.
* M2: Preflight now requires HTTP 400 with `invalid_request`, verified against
   the actual in-process HTTP adapter rather than an invented 422 stub.
* M3: Canonical model comparisons accept omitted or explicit null answers across
   HTTP/MCP while rejecting extras, malformed values and mismatched stored results.
* M4: The harness consumes actual deployment-verifier JSON and validates source,
   image, revision and authentication proof, with separate approved database
   binding. No paid-call authorization is inferred from deployment verification.
* Harness corrections passed 145 offline regressions, including the real HTTP
   adapter and stubbed deployment-script producer. Ruff, formatting and strict
   mypy passed. The parent combined suite passed 429 tests with 91.28% coverage;
   live tests remain skipped without explicit consent.

Authoritative final status and post-documentation evidence are recorded in
[the consolidated review](../../2026-09-16/ask-my-human-tight-mvp-plan-review.md).
