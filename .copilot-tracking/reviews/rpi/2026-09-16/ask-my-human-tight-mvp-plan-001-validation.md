---
title: AskMyHuman Phase 1A Validation
description: Read-only validation of all eight Phase 1A application workstreams.
ms.date: 2026-09-16
---

## Executive Details

Status: Failed. Phase 1A comparison is complete. Required authentication,
callback, lifecycle, and telemetry guarantees are not satisfied. The resumed
review used source and installed SDK evidence only; completed tests and probes
below were preserved, not repeated.

Scope: Phase 1A steps 1A.1 through 1A.8. Only this validation artifact was
modified. Existing user modifications were preserved. No deployment, Azure calls,
publishing, commits, dependency changes, or secret-file reads were performed.
The parent owns the immediate service lifecycle repair; its verification remains
outstanding and is not implied by this report's completion.

## Validation Inputs

* [.copilot-tracking/plans/2026-09-15/ask-my-human-tight-mvp-plan.instructions.md](.copilot-tracking/plans/2026-09-15/ask-my-human-tight-mvp-plan.instructions.md)
* [.copilot-tracking/changes/2026-09-15/ask-my-human-tight-mvp-changes.md](.copilot-tracking/changes/2026-09-15/ask-my-human-tight-mvp-changes.md)
* [.copilot-tracking/research/2026-09-15/tight-mvp-scope-research.md](.copilot-tracking/research/2026-09-15/tight-mvp-scope-research.md)
* [.copilot-tracking/details/2026-09-15/ask-my-human-tight-mvp-details.md](.copilot-tracking/details/2026-09-15/ask-my-human-tight-mvp-details.md)
* [.copilot-tracking/plans/logs/2026-09-15/ask-my-human-tight-mvp-log.md](.copilot-tracking/plans/logs/2026-09-15/ask-my-human-tight-mvp-log.md)

## Requirements Matrix

All five requested artifacts have been read in full. The eight checked steps
match eight changes-log sections, and all named Phase 1A source and test surfaces
exist. Completion claims are not sufficient evidence of runtime correctness.

* 1A.1: [Requirements](.copilot-tracking/details/2026-09-15/ask-my-human-tight-mvp-details.md#L243) match the [persistence claim](.copilot-tracking/changes/2026-09-15/ask-my-human-tight-mvp-changes.md#L79).
Atomic admission, subject-scoped replay/conflict, first-terminal arbitration,
restart visibility, expiry, and purge have the preserved seven-test evidence.
Partial: the successful-callback expiry predicate is missing (F5); background
expiry does not coordinate call cleanup (F9).
* 1A.2: [Requirements](.copilot-tracking/details/2026-09-15/ask-my-human-tight-mvp-details.md#L293) match the [orchestration claim](.copilot-tracking/changes/2026-09-15/ask-my-human-tight-mvp-changes.md#L85).
Creator/replay separation, polling, durable sanitized errors, and terminal
arbitration are present. Failed: hard deadlines, cancellation during awaited
operations, connected-driven recognition, and maintenance recovery fail or
lack required control flow (F4, F8, F9). Parent repair is not yet revalidated.
* 1A.3: [Requirements](.copilot-tracking/details/2026-09-15/ask-my-human-tight-mvp-details.md#L336) match the [telephony claim](.copilot-tracking/changes/2026-09-15/ask-my-human-tight-mvp-changes.md#L91).
One create command, fixed approval choices, DTMF, trimmed speech, six fixtures,
and no audio relay/retry are present. Failed: connected-event dispatch,
technical failure mapping, call correlation, and playback sequencing are
incomplete (F3, F4, F10).
* 1A.4: [Requirements](.copilot-tracking/details/2026-09-15/ask-my-human-tight-mvp-details.md#L387) match the [security claim](.copilot-tracking/changes/2026-09-15/ask-my-human-tight-mvp-changes.md#L97).
HTTP role/allowlist enforcement and mocked JWT signature, issuer, audience,
expiry, caching, rotation, and network-failure tests are present. Partial:
MCP authorization, configured audience separation, callback call-ID checking,
and discovery resource bounds are incomplete (F1, F2, F3, F11).
* 1A.5: [Requirements](.copilot-tracking/details/2026-09-15/ask-my-human-tight-mvp-details.md#L429) match the [HTTP adapter claim](.copilot-tracking/changes/2026-09-15/ask-my-human-tight-mvp-changes.md#L102).
Thin injectable routers, stable HTTP error mapping, JWT-before-body ordering,
disconnect signaling, and duplicate acknowledgement have scoped coverage.
Partial: authenticated callback conversion loses required information (F3,
F4); cancellation signaling does not repair the service wait itself (F8).
* 1A.6: [Requirements](.copilot-tracking/details/2026-09-15/ask-my-human-tight-mvp-details.md#L472) match the [platform API claim](.copilot-tracking/changes/2026-09-15/ask-my-human-tight-mvp-changes.md#L107).
Passed within the local scope: content-free liveness/readiness, opened-pool
gating, and configured OAuth resource metadata. Actual platform probe
routing and tenant/client acceptance remain external gates, not local defects.
* 1A.7: [Requirements](.copilot-tracking/details/2026-09-15/ask-my-human-tight-mvp-details.md#L508) match the [MCP claim](.copilot-tracking/changes/2026-09-15/ask-my-human-tight-mvp-changes.md#L112).
One tool, checked-schema equality, direct dispatch, structured errors, and
cancellation signals have scoped coverage. Failed: real transport principal
mapping and authorization are absent; exception logging leaks content (F1,
F6). The target client's timeout/cancellation demonstration remains external.
* 1A.8: [Requirements](.copilot-tracking/details/2026-09-15/ask-my-human-tight-mvp-details.md#L548) match the [observability claim](.copilot-tracking/changes/2026-09-15/ask-my-human-tight-mvp-changes.md#L117).
Typed telemetry helpers, isolated sentinel tests, and explicit Psycopg 2
instrumentation exclusion exist. Failed: helper tests miss an actual exception
log leak and production instrumentation is incomplete (F6, F7).

## Confirmed Findings

### F1 Critical: MCP Authentication And Authorization Are Disconnected

Confirmed for steps 1A.4 and 1A.7. The mounted transport has no authentication
bridge, while the HTTP router alone receives the trusted platform-principal
parser. See [main.py](src/ask_my_human/main.py#L165) and
[server.py](src/ask_my_human/mcp_adapter/server.py#L189).
The MCP adapter requires an SDK access-token context rather than the Container
Apps header. Platform-authenticated calls therefore lack a usable principal.
When a token context is supplied, it checks only the subject and does not enforce
the required role or application allowlist. The prior roleless/non-allowlisted
token probe already confirmed this second defect; it was not repeated.

Recommended fix: inject one shared authorization function into both transports,
bridge only platform-trusted identity into each MCP request, enforce
`AskHuman.Invoke` and the configured application allowlist before dispatch, and
use the same stable subject identifier for HTTP and MCP idempotency. Add mounted
transport tests for an authorized principal, missing identity, missing role, and
disallowed application. Do not treat an arbitrary caller header as trusted when
running outside the Container Apps authentication boundary.

Installed SDK inspection confirms that authentication middleware is installed
only when authentication options and a token verifier are supplied, and the token
context defaults to `None`. The existing [MCP fixture](tests/unit/mcp_adapter/test_server.py#L69)
sets that context manually; it does not validate mounted transport identity.

### F2 Critical: Callback Audience Is Conflated With The Webhook URL

Confirmed specification deviation for 1A.3/1A.4. The
[research requires the ACS resource audience](.copilot-tracking/research/2026-09-15/tight-mvp-scope-research.md#L214),
with the [detailed security requirement](.copilot-tracking/research/subagents/2026-09-15/service-contract-decision-research.md#L480)
specifying the resource ID. [Settings](src/ask_my_human/config.py#L24)
requires an HTTP URL; [gateway construction](src/ask_my_human/telephony/acs_client.py#L47)
appends the callback path to it; [validator construction](src/ask_my_human/main.py#L143)
uses the identical value as JWT audience. These are independent identifiers.
The URL-valued mocked [JWT test audience](tests/unit/security/test_acs_callback.py#L16)
cannot demonstrate compatibility with real ACS tokens.

Recommended fix: introduce separate validated public callback URL and ACS token
audience settings through the foundation owner, wire each to its consumer, and
test distinct synthetic values without coercing the resource identifier into a
URL. The exact tenant resource identifier and acceptance of a legitimate ACS
token are external deployment gates; no real-token rejection was reproduced here.

### F3 Critical: Authenticated Callbacks Lose Call-Connection Correlation

Confirmed missing check for 1A.3/1A.4/1A.5. Research requires verification of the
[stored call identifier when available](.copilot-tracking/research/subagents/2026-09-15/service-contract-decision-research.md#L488).
The parser requires `callConnectionId`, but
[conversion](src/ask_my_human/telephony/events.py#L49) drops it and
[CallEvent](src/ask_my_human/domain/models.py#L38) has no field for it.
[Callback handling](src/ask_my_human/application/service.py#L89) therefore uses
only the request UUID and pending state. A validly authenticated event with the
right request context but a different call ID is not checked against the row.
This is not a demonstrated unsigned-token bypass.

Recommended fix: retain call ID through the internal event contract, compare it
with the persisted call before media or terminal work, and define safe handling
for an event racing initial call-ID attachment. Test matching and mismatched IDs,
duplicate delivery, and the attachment race. Coordinate the internal contract
change with the foundation and parent lifecycle owners.

### F4 Critical: Callback Mapping Drops Lifecycle And Technical Events

Confirmed for 1A.2/1A.3/1A.5. [Connected events](src/ask_my_human/telephony/events.py#L52)
map to `None`; [composition](src/ask_my_human/main.py#L102) discards them.
[Service startup](src/ask_my_human/application/service.py#L101) instead starts
recognition immediately after create/attach/read, before a connected callback.
Unclassified create failures also map to `None`; their `dependency_failure`
property is never consumed. [Recognition failures](src/ask_my_human/telephony/events.py#L62)
all become `no_answer`, including technical 500 responses.
Preserved probes: `technical_create_dispatched_events=0` and
`recognize_500=no_answer`.

Recommended fix: preserve connected and technical-failure events through the
internal contract. Start recognition once, only after a correlated connected
event and before the cutoff; use a durable once-only guard for duplicates/races.
Map documented silence/no-match codes to `no_answer`, technical errors to the
existing sanitized durable error path, and unknown disconnect codes to
`disconnected` as specified. Test through callback conversion and service, not
only the parser property. Parent lifecycle edits must consume these events.

### F5 Critical: Terminal SQL Does Not Reject Expired Success

Confirmed for 1A.1/1A.2. The
[successful terminal update](src/ask_my_human/persistence/repository.py#L101)
checks only `status = 'pending'`; the separate expiry loop cannot make that check
atomic with elapsed time. The preserved service probe records approval at age
300 seconds. SQL inspection confirms the real repository also lacks the guard;
the probe is not represented as a PostgreSQL-specific reproduction.

Recommended fix: guard successful response updates with database time earlier
than `expires_at`, within the same SQL statement. Keep deadline/cancellation
updates able to expire overdue rows; do not add a blanket expiry guard to all
terminal results. Coordinate the 205-second cutoff with the parent lifecycle
repair. Add a PostgreSQL test with an overdue pending row and a success-versus-
expiry race. The existing [terminal race test](tests/integration/persistence/test_repository.py#L95)
checks one winner, not the deadline predicate.

### F6 Critical: Unexpected MCP Exceptions Leak Sensitive Log Content

Confirmed for 1A.7/1A.8. [The catch-all handler](src/ask_my_human/mcp_adapter/server.py#L153)
uses `logger.exception`, which includes the exception message and traceback.
Preserved probe: `mcp_exception_log_leaks=True`. Sanitizing the public error does
not sanitize the log. The [adapter test](tests/unit/mcp_adapter/test_server.py#L185)
checks returned text only. Disabling exception capture on custom
[telemetry spans](src/ask_my_human/observability.py#L162) does not affect logging.

Recommended fix: emit only an approved fixed error code and random request
correlation, without raw exception text, traceback, or chained exceptions.
Capture actual adapter logs as well as responses in a sentinel regression test.
Extend composed telemetry tests to SDK/ASGI exception paths; Azure exporter
ingestion remains an external gate, not proven safe by helper-only tests.

### F7 Critical: Required Operational Telemetry Is Not Connected

Confirmed missing functionality for 1A.8. Source call-site inspection finds only
[ASK/CALLBACK completion records](src/ask_my_human/application/service.py#L208).
No production caller invokes [dependency failure recording](src/ask_my_human/observability.py#L171)
or [pending updates](src/ask_my_human/observability.py#L189); the gauge starts at
zero and stays zero. No repository, create-call, or recognition operation uses
the corresponding custom span. [Record](src/ask_my_human/observability.py#L98)
creates an empty span after the work, so it does not time the operation itself.
Durable errors are raised before the service records a terminal result.

The [all-span test](tests/unit/test_observability.py#L111) manually opens every
span, and the [metric test](tests/unit/test_observability.py#L132) manually changes
the gauge. Neither demonstrates production instrumentation coverage.

Recommended fix: extend the frozen telemetry port with the minimum required
typed operations through its owner; instrument actual repository, call-create,
recognition, request, and callback work with random request correlation. Update
pending state on admission and every terminal/maintenance path, including
startup reconciliation, and emit sanitized dependency failures. Verify the
composed service with in-memory exporters and a pending-to-terminal flow.

### F8 Critical: Preserved Lifecycle Failures Await Parent Repair

Previously confirmed for 1A.2; no new service investigation or test repetition.
[Unbounded create/recognize awaits](src/ask_my_human/application/service.py#L101)
precede [the cancellation/deadline polling loop](src/ask_my_human/application/service.py#L129),
and [hang-up](src/ask_my_human/application/service.py#L176) is also unbounded.
Preserved results: a simulated 300-second create returns only at 300 seconds;
task cancellation leaves `pending` with zero hang-ups.

Recommended fix and parent verification: enforce one shared monotonic budget
over all blocking operations, interrupt creator-owned work on cancellation,
persist the winning terminal result, and bound/shield cleanup within the
remaining budget. Joined-waiter cancellation must not terminate the call. Cover
stalled create, repository access, recognition, and hang-up; coordinate F3-F5.
The parent's forthcoming changes are not considered verified by old test totals.

### F9 Major: Maintenance Stops On Errors And Cannot Clean Up Calls

Confirmed for 1A.1/1A.2. [The loop](src/ask_my_human/application/maintenance.py#L48)
lets the first repository exception terminate the task. Preserved probe:
`maintenance_attempts=1`. [Expiry](src/ask_my_human/persistence/repository.py#L131)
returns only a count, and maintenance receives no gateway. Thus stale expiry
can release admission without attempting cleanup of the old persisted call,
particularly after process replacement. A still-active call is a risk of this
missing path, not a reproduced paid-call overlap.

Recommended fix: retain periodic execution after transient errors with bounded
delay and content-free failure reporting, while propagating shutdown
cancellation. Return/claim expired call identifiers for bounded best-effort
cleanup through the existing in-process owner; add no worker or redial. Test
one transient failure followed by recovery and a restarted stale active call.
Rechecking readiness alone does not repair stopped maintenance.

### F10 Major: Hang-Up Does Not Wait For Acknowledgement Playback

Confirmed sequencing deviation for 1A.3. [The gateway](src/ask_my_human/telephony/acs_client.py#L107)
awaits `play_media` then immediately hangs up. Installed ACS SDK source shows
that `play_media` submits a media command; it does not await a playback-complete
event. The [event enum](src/ask_my_human/telephony/events.py#L12) has no
`PlayCompleted`/`PlayFailed` handling. The existing
[acknowledgement test](tests/unit/telephony/test_acs_client.py#L129) checks mocked
command order only. Actual audible truncation was not tested.

Recommended fix: correlate acknowledgement playback completion/failure and then
hang up, with a bounded fallback inside the cleanup budget. Keep terminal result
arbitration independent of that callback so already-terminal rows can still
trigger cleanup. Test delayed completion, failed/missing playback callback, and
duplicate callback without replaying the acknowledgement.

### F11 Major: Discovery Bounds Apply After Download And Allow Refresh Churn

Confirmed for 1A.4. [Document fetching](src/ask_my_human/security/acs_callback.py#L161)
buffers the complete HTTP response before checking `MAX_DOCUMENT_BYTES`; this
is a parsed-document limit, not a download-memory limit. HTTPX's configured
timeout bounds network inactivity phases, not total elapsed download time.
[Unknown key IDs](src/ask_my_human/security/acs_callback.py#L75) force a new key
fetch before signature validation. The refresh lock coalesces some concurrent
requests but sequential unknown IDs can repeatedly fetch fresh keys.

Recommended fix: stream and cap decoded bytes while reading, enforce a total
discovery deadline including lock acquisition, and add a bounded forced-refresh
cooldown or negative cache while retaining legitimate rotation support. Add
mocked oversized/slow-stream and repeated-unknown-key tests. Existing key-set
size and TTL limits are valid; unbounded retained key-cache growth is rejected
as a finding. No discovery traffic or resource-exhaustion probe was run here.

## Resolved Concerns And External Gates

* Rejected: readiness succeeds before initial database availability in the
composed application. [Pool opening](src/ask_my_human/persistence/pool.py#L24)
awaits `wait()`, and [lifespan](src/ask_my_human/main.py#L187) waits for that
before serving. [Readiness](src/ask_my_human/api/health.py#L29) checks the opened
state without paid dependencies as planned. Continued database reachability
after startup is not demonstrated by `closed`; active health checking would
be a separate requirement, not evidence that the initial gate is broken.
* Rejected: callback signature/issuer/expiry validation is absent. It exists and
the preserved mocked tests cover it. Audience configuration is a separate
confirmed defect (F2), not a cryptographic primitive failure.
* Rejected: first-terminal SQL permits overwriting an already-terminal row, or
purge deletes pending rows. Both are guarded; the seven preserved database
tests support arbitration and retention behavior. F5 concerns an overdue row
that is still pending; F9 concerns physical call cleanup and loop recovery.
* Rejected: the approved internal durable-error extension is unexplained scope
drift. Planning-log DD-03 records it, and restart error replay has integration
evidence. Public wire schemas remain unchanged by that extension.
* External: platform header authenticity, header stripping, probe routing,
deployed Entra role/client assignments, and actual OAuth metadata discovery.
[Local metadata](src/ask_my_human/api/oauth_metadata.py#L18) advertises the
configured application URI and tenant issuer. The target registration and
client must demonstrate acceptance; no tenant values were inspected.
* External: the actual ACS audience, region/number eligibility, carrier-specific
codes, acknowledgement audibility, and real-call outcomes. F2/F4/F10 must be
repaired before their respective live checks can establish acceptance.
* External: Azure Monitor/SDK/ASGI exported telemetry and sensitive-sentinel
absence in Application Insights. The MCP log leak is confirmed locally;
broader automatic-instrumentation leakage is not claimed as reproduced.
* External: DR-01 through DR-05 approvals, including retention and a target MCP
client's 225-second timeout/cancellation behavior. These are release gates,
not reasons to treat missing local functionality as complete.

## Coverage And Change-Log Reconciliation

All eight phase steps were matched to the changes log and reviewed against their
requirements. One step (1A.6) has no confirmed local defect within its defined
scope; the other seven are incomplete or fail required behavior. This is not a
code-coverage percentage or release approval. Findings comprise eight Critical
items and three Major items; no independent Minor finding is retained.

The checked boxes and historical statement that all Phase 1A implementations
are independently testable do not establish their behavioral completion. The
current changes log already identifies later integration/release files as
historical follow-on work. The nearby [composition root](src/ask_my_human/main.py)
was reviewed only to verify phase exports, callback conversion, auth wiring, and
readiness. It is not a new Phase 1A-owned file or an unapproved architecture.
The working-tree check found concurrent edits to
[tests/e2e/test_live_call.py](tests/e2e/test_live_call.py), outside this validation
slice; they were neither reviewed nor changed. Plans, logs, research, settings,
implementation, and tests were left untouched by this validator.

## Tested Outputs

* Scoped unit suite: `95 passed, 1 warning in 2.33s`. The warning is Starlette's
deprecated AnyIO blocking-portal alias.
* PostgreSQL integration suite: `7 passed in 9.22s`, using disposable local
PostgreSQL 16 and the already cached testcontainer images.
* No-network runtime probes: `slow_create=300s`, `late_callback=approved`,
`cancelled_task_state=pending`, `hangups=0`, `maintenance_attempts=1`,
`technical_create_dispatched_events=0`, `recognize_500=no_answer`,
`mcp_exception_log_leaks=True`, and roleless/non-allowlisted MCP principal accepted.
* Pylance discovery is unavailable in this session. Existing virtual-environment
executables and installed SDK source supply runtime evidence; no selected-editor
interpreter or Pylance diagnostic claims are made.

These results were already recorded by the existing validation session and were
preserved on resumption. The changes log's broader 150-test total was not
independently reproduced here. No new product tests, Python execution,
deployment, or paid call was performed during this continuation. New findings
are explicitly based on source/installed-SDK inspection rather than fabricated
runtime outcomes. Product and test files have not been edited by this validator.

Report-only validation: editor diagnostics reported no errors after the findings
update. All 65 workspace-relative file links and line bounds passed validation.
These are document checks, not product verification.

## Release Evidence And Open Questions

Recommended next validations, not completed during this continuation:

* [ ] After the parent repair, rerun focused lifecycle deadline/cancellation and connected-callback race regressions, including stalled dependencies and bounded cleanup.
* [ ] Exercise mounted MCP authorization with allowed, roleless, disallowed, and missing platform identities, without manually seeding SDK auth context.
* [ ] Validate separate callback URL/audience settings, mismatched call IDs, technical callback failures, and bounded discovery with synthetic data.
* [ ] Add a PostgreSQL overdue-success race and restart-expiry cleanup test; verify maintenance survives a transient database failure.
* [ ] Exercise composed spans/metrics and real exception logging with in-memory exporters and sensitive sentinels, plus delayed acknowledgement completion.
* [ ] Run each changed owner's focused tests, type checks, and lint checks after implementation fixes, then the separately authorized integration/release gates.
* [ ] With separate authorization and DR approvals, verify platform auth/probes, legitimate ACS callbacks, target MCP client behavior, live calls, and Application Insights redaction.

Clarifying questions for release owners, not blockers to this read-only review:

* Which sanitized deployment evidence establishes the ACS resource audience and the Entra application-role/client assignments after F1/F2 are corrected?
* Which target MCP client and approved environment will demonstrate the required timeout, cancellation, and metadata discovery behavior?
* Who approves the 24-hour payload and 30-day content-free telemetry retention defaults?

No further local clarification is required to act on the confirmed findings.
