---
title: Live Harness Validation Research
description: Scoped evidence for live harness gates and offline regressions.
ms.date: 2026-09-16
---

## Scope

Investigate and implement review 004 F04, F05, F06, F13 and review 005 M4, M5
in tests/e2e/test_live_call.py and tests/unit/test_live_harness.py.
No live calls, credentials, secret files, Azure operations, publication, or commits.

## Findings

The live matrix in .copilot-tracking/details/2026-09-15/ask-my-human-tight-mvp-details.md
requires distinct outcomes, MCP, independent call-attempt evidence, duplicate callbacks,
privacy and retention checks. Existing partial edits must be preserved.
The development query SDK is already declared in pyproject.toml.

## Validation

Local implementation and scoped verification: Complete. Live acceptance: Blocked.

* Ruff check and format passed for both owned test files.
* Strict mypy passed for both owned test files.
* 64 no-network regression tests passed with socket connections and credential
	construction blocked. Dummy responses exercise authentication, terminal results,
	provider attempts, pending joins, cancellation, privacy, and retention cleanup.
* Default selection passed 64 offline tests and deselected all 20 live scenarios.
* Explicit live selection with RUN_LIVE_AZURE_TESTS removed skipped all 20 scenarios.
	No live fixture or test body ran.
* Editor diagnostics and scoped git diff whitespace checks passed.

## Implemented Gates

The session fixture graph validates approval before credential creation, then checks
authentication and readiness before any paid-call fixture. Invalid request bodies
make negative authentication probes cost-free even if the boundary is broken.

LIVE_APPROVAL_JSON and LIVE_DEPLOYMENT_EVIDENCE_JSON are parsed only during opted-in
execution. Their models in tests/e2e/test_live_call.py are the input contracts.
They bind the exact HTTPS origin, digest-qualified image, revision, full database
DSN SHA-256, isolated-database approval, fresh healthy/ready/running deployment
metadata, and nonblank decision references for DR-01 through DR-05. Each selected
pytest scenario name also needs an operator setup record. No carrier case skips.

The approval supplies provider_evidence_file, telemetry_evidence_file,
telemetry_workspace, telemetry_settle_seconds (60 through 600), and an MCP client
timeout of 225 through 240 seconds. These read-only JSON exports must be supplied
by an authorized operator, not generated from database row counts by the harness.
Provider exports require complete time-window coverage and per-attempt identities
correlated with request and call IDs. Concurrent replay additionally requires a
timestamped pending-join record. Duplicate callback proof requires distinct accepted
delivery receipts for the same event, including receipt after terminal completion.
The harness does not add production hooks or manufacture provider evidence.

The result gate enforces canonical public results, exact outcomes, nonblank answers,
full stored/wire equality, and measured caller completion within 210 seconds.
Cancellation requires an observed pending correlated call, a cancelled result within
15 seconds, and stable replay. HTTP and the installed MCP v2 transport are covered.

Telemetry is mandatory, with no importorskip. Query access is checked before calls.
The privacy scenario checks prompt, spoken answer, phone, idempotency key, agent
authorization, callback body/query sentinel, database URL, and telemetry connection
string. It waits for both a bounded settling period and an approved export watermark,
rejects partial query results, and requires positive request-ID correlation. Error
messages suppress sensitive content and harness-side SDK logging is disabled.

Retention uses the production purge path, tolerates a maintenance worker winning the
delete race, and cleans up both controlled IDs in finally on success or failure.

The azure-monitor-query dev dependency and lock changes were already present during
this work; this agent did not modify either dependency file or other product files.

## External Gates

Deployment approval, immutable revision evidence, isolated database approval,
carrier setup, provider evidence, and authorized live execution remain external.

* [ ] Obtain approved DR records, current deployment metadata, and the isolated DB binding.
* [ ] Arrange carrier-specific silence, ring-out, busy, decline, disconnect, and forced
	deadline scenarios. Unsupported cases block acceptance unless separately approved
	as release limitations; the harness does not silently pass them.
* [ ] Supply actual create-attempt, pending-join, and accepted duplicate-delivery exports.
* [ ] Supply telemetry export-watermark evidence and actual configured sensitive values
	during a separately authorized live invocation; speak the approved answer sentinel.
* [ ] Execute the paid live matrix and target-client qualification only after authorization.
* [ ] Parent owner runs the repository-wide gate; only the owned slice was validated here.

No clarifying question blocks the local implementation. Operator approvals and
external evidence cannot be produced within this no-live authorization.