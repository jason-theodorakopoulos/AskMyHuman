<!-- markdownlint-disable-file -->
# Ask My Human Owned-Scope Implementation Quality Review

## Metadata And Status

* Date: 2026-09-16
* Scope: full-quality audit and corrections within the assigned composition,
  configuration, security, MCP, observability, health, and associated test files
* Overall status: Complete for the assigned scope; not a whole-project release approval
* Open local findings: 0 critical, 0 major, 0 minor
* Consolidated findings addressed: 6 critical, 2 major
* Follow-up groups: 2, both outside this assignment

Related artifacts:

* [Implementation plan](.copilot-tracking/plans/2026-09-15/ask-my-human-tight-mvp-plan.instructions.md)
* [Changes log](.copilot-tracking/changes/2026-09-15/ask-my-human-tight-mvp-changes.md)
* [Research](.copilot-tracking/research/2026-09-15/tight-mvp-scope-research.md)
* [Finalized Phase 1A report](.copilot-tracking/reviews/rpi/2026-09-16/ask-my-human-tight-mvp-plan-001-validation.md)
* [Finalized composition report](.copilot-tracking/reviews/rpi/2026-09-16/ask-my-human-tight-mvp-plan-003-validation.md)

The two finalized RPI reports supplied the detailed requirements and findings.
Their overlapping findings are consolidated below rather than counted twice.
This pass used regular tools and an isolated local execution runner; it does
not claim fresh parallel subagent reviews or independent validation of every
implementation phase. Existing changes from other agents were preserved.

## Security And Authentication

### Q1 Critical: Shared HTTP And MCP Authorization Corrected

The shared trusted Container Apps principal parser is injected into mounted MCP
and HTTP dispatch. Existing corrections removing the SDK access-token fallback
and sanitizing unexpected MCP errors were retained and verified. The standalone
MCP factory now also accepts the authenticator. Blank identity claims fail
authentication; stable object identifiers take precedence over distinct OIDC
pairwise subject claims. Role and application allowlist checks remain mandatory.

Evidence: [principal parser](src/ask_my_human/security/agent.py#L34),
[MCP authentication](src/ask_my_human/mcp_adapter/server.py#L193),
[standalone factory](src/ask_my_human/mcp_adapter/server.py#L223),
[mounted authorization matrix](tests/integration/test_asgi_app.py#L545),
[fallback rejection](tests/unit/mcp_adapter/test_server.py#L193), and
[object identity regression](tests/unit/security/test_agent.py#L32).

### Q2 Critical: Callback Endpoint And Audience Separated

`acs_callback_url` is a required full HTTPS endpoint ending in
`/v1/callbacks/acs`, without credentials, query, or fragment. The independent
`acs_callback_audience` is a nonblank string for the ACS immutable resource
identifier, not an HTTP URL type. Composition passes only the audience to the
JWT validator. Synthetic test fixtures use distinct endpoint and identifier
values. No environment file was read or changed by this pass.

Evidence: [URL validation](src/ask_my_human/config.py#L40),
[audience validation](src/ask_my_human/config.py#L54),
[construction](src/ask_my_human/main.py#L113), and
[configuration tests](tests/unit/test_config.py#L106).

### Q3 Major: OIDC And JWKS Downloads Bounded

Discovery uses streamed reads capped at 262144 bytes and closes rejected streams.
Unexpected content encodings and redirects are rejected. One asyncio timeout
covers validation, including refresh-lock waits and both metadata/key downloads.
A 30-second per-endpoint cooldown bounds failed discovery and unknown-key churn;
valid cached keys remain usable, and key rotation refreshes after the cooldown.

Evidence: [total deadline](src/ask_my_human/security/acs_callback.py#L73),
[streamed fetching](src/ask_my_human/security/acs_callback.py#L176),
[cooldown regressions](tests/unit/security/test_acs_callback.py#L214), and
[oversized/slow stream regressions](tests/unit/security/test_acs_callback.py#L244).

## Composition And Lifecycle

### Q4 Critical: Callback Lifecycle And Correlation Preserved

Composition forwards the coordinated parser's connected, dependency-failed,
play-completed, and play-failed domain events without a terminal-only filter.
Owned integration assertions now require call IDs and ACS codes. Callback
conversion tests cover all four new event types and technical recognition
failures. The parser/domain implementations themselves remain with their owners.

Evidence: [batch conversion](src/ask_my_human/main.py#L94) and
[event forwarding regressions](tests/integration/test_asgi_app.py#L638).

### Q5 Critical: Maintenance Failure Is Visible And Shutdown Drains

Readiness requires both maintenance tasks to exist and remain running, in
addition to settings and an opened pool. Failed, cancelled, or unexpectedly
returned tasks make readiness unavailable; liveness remains independent.
Shutdown cancels both tasks, gathers every result, and only then raises grouped
failures. Pool and client closure remains after maintenance drainage.

Evidence: [task readiness](src/ask_my_human/main.py#L168),
[health gate](src/ask_my_human/api/health.py#L34),
[drainage](src/ask_my_human/main.py#L241), and
[expiry/purge failure tests](tests/integration/test_asgi_app.py#L378).

### Q6 Major: Startup Cancellation Cleans The Partially Open Pool

Pool closure is registered before awaiting pool opening. Cancelled startup now
unwinds both partially initialized pool resources and the remaining clients.

Evidence: [application lifespan](src/ask_my_human/main.py#L162) and
[cancelled startup regression](tests/integration/test_asgi_app.py#L424).

## Telemetry And Privacy

### Q7 Critical: MCP Error Logging Is Content-Free

The existing fixed-message MCP error log is retained. Regression assertions
cover emitted logs, public errors, and absence of exception traceback capture.
No caller-controlled prompt, exception message, or access token is logged by
that handler.

Evidence: [fixed error log](src/ask_my_human/mcp_adapter/server.py#L158) and
[MCP regression suite](tests/unit/mcp_adapter/test_server.py).

### Q8 Critical: Real ASGI And Shared Operational Telemetry Connected

The returned FastAPI app explicitly installs idempotent content-free ASGI
instrumentation. It creates real SERVER spans around request execution,
propagates validated traceparent correlation, and exports only HTTP method and
numeric status. It does not capture URLs, headers, bodies, response content,
exception events, stack traces, or exception status descriptions.

This intentionally uses explicit middleware rather than default FastAPI
auto-instrumentation, whose automatic exception and request attributes exceed
the content-free requirement. Azure Monitor's default SDK, HTTP, framework,
and Psycopg 2 instrumentation is disabled, along with automatic logging,
live metrics, and performance counters. Manual approved spans and metrics
remain enabled.

The concrete telemetry class supports the shared typed span and dependency
failure operations. Composition passes telemetry to the repository and both
gateway and telemetry to maintenance. Startup pending reconciliation remains
owned by maintenance; main performs no separate initial count.

Evidence: [HTTP instrumentation](src/ask_my_human/observability.py#L59),
[port mapping](src/ask_my_human/observability.py#L184),
[exporter configuration](src/ask_my_human/observability.py#L284),
[factory wiring test](tests/integration/test_asgi_app.py#L37),
[actual composed server span](tests/integration/test_asgi_app.py#L297), and
[success/exception sentinel tests](tests/unit/test_observability.py#L217).

## Validation Outputs

All final commands used the configured local Python 3.12 virtual environment.
An isolated subprocess runner captured exact commands and exit codes because
shared terminal sessions intermittently returned another agent's command output.
Earlier mismatched terminal output is not relied upon as final evidence.

Source scope: main, security, mcp_adapter, config, observability, and api/health.
Test scope: unit/security, unit/mcp_adapter, unit/test_config,
unit/test_observability, unit/api/test_health, integration/test_asgi_app,
and the shared root test fixture.

| Check | Result | Output |
| --- | --- | --- |
| Scoped pytest, excluding application_container | Pass, exit 0 | 83 passed, 1 deselected, 1 warning in 2.31s |
| Ruff check on source/test scope | Pass, exit 0 | All checks passed |
| Ruff format --check on source/test scope | Pass, exit 0 | 17 files already formatted |
| Mypy on source/test scope | Pass, exit 0 | Success: no issues found in 17 source files |
| git diff --check on source/test scope | Pass, exit 0 | No output |
| Editor diagnostics on touched production files and principal integration/telemetry tests | Pass | No errors found |

The warning is the installed Starlette test client's deprecated AnyIO
BlockingPortal alias. No unrelated dependency update was attempted.

## Follow-Up Work

### Deferred Outside Assigned Scope

1. The parent must run combined repository, service, maintenance, telephony,
   database, container, schema, and infrastructure gates after all agents finish.
   Shared constructor compatibility passed scoped mypy here, but that does not
   independently verify the other owners' runtime behavior. No service, ports,
   domain, repository, maintenance, telephony, Docker, infrastructure, scripts,
   end-to-end tests, README, or other tracking artifact was modified by this pass.
2. Separately authorized release validation must establish Container Apps header
   stripping and role assignments, actual ACS audience and webhook delivery,
   client timeout/cancellation behavior, and Application Insights redaction.
   No deployments, paid calls, live Azure access, secret-file reads, commits,
   publishing, or container smoke test were performed here.

### Discovered During Review

No unresolved local follow-up. Blank principal handling and object-ID precedence
were corrected within the owned security slice. Test doubles were updated for
the coordinated stale-call expiry method rather than weakening production
contracts or changing another owner's implementation.