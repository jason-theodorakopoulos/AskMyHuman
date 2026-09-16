---
title: AskMyHuman
description: Synchronous human approval and spoken answers for authenticated agents through Azure Communication Services.
---

## Overview

Human-in-the-loop for autonomous agents. AskMyHuman lets an authenticated agent
place one synchronous request, an approval or a free-form question, that is
answered by a human over a single phone call, and returns a terminal result to
the agent in the same request/response turn.

## Product Scope (Tight MVP)

1. An agent asks for either an `approval` or an `input` (free-form
   answer) through an MCP tool or the HTTP API.
2. Every request goes to the one human configured through the
   `MY_MOBILE_NUMBER` setting. There is no support for multiple humans, roles,
   or per-agent routing.
3. The service places one outbound phone call through Azure
   Communication Services (ACS).
4. The call plays the request's prompt so the human has enough
   context to decide or answer.
5. Approvals are captured as approve/reject choices; input
   requests capture one spoken answer transcribed to text.
6. Requests move from `pending` to `responded` or `expired` and
   never resume once terminal.
7. Asynchronous resume is unsupported. Subject-scoped idempotent invocations
  can join a pending wait or replay a stored terminal result without another
  call or an extended deadline.
8. Escalation is out of scope. No retries, no additional channels, no
   multiple humans/roles, and no escalation paths.

### Explicit Exclusions

* Multiple humans, roles, or per-agent routing.
* Retries, escalation, or additional notification channels (SMS, email, chat).
* Asynchronous resume, background retrieval, or reopening a terminal request.
* Multi-turn conversation, clarification loops, or free-form voice dialogue.
* Horizontal scaling: the Container Apps deployment is fixed to exactly one
  replica (minimum and maximum) for this MVP.
* Private networking (VNet integration): Azure resources use public service
  endpoints protected by TLS, managed identity, and application-level
  authentication instead of a VNet.

Follow-on ideas (multiple humans, escalation, retries, multi-turn voice,
horizontal scaling, private networking) are tracked in
[.copilot-tracking/plans/logs/2026-09-15/ask-my-human-tight-mvp-log.md](.copilot-tracking/plans/logs/2026-09-15/ask-my-human-tight-mvp-log.md) and are
**not** implemented here.

## Architecture

* Azure Container Apps hosts the AskMyHuman API, MCP adapter, and
  orchestration logic as a single FastAPI/Uvicorn ASGI application, fixed to
  one replica.
* Azure Database for PostgreSQL provides durable storage for request state,
  idempotency, and terminal results, accessed with Psycopg 3 async pooling and
  Alembic migrations.
* Azure Communication Services (ACS) Call Automation places the one
  outbound phone call per request and drives the call through callbacks.
* ACS Play and Recognize with Azure AI Speech captures the human's
  approve/reject choice or spoken free-form answer using one bounded
  choice/speech-recognition action. **This replaces the Microsoft Foundry
  Voice Live API named in earlier product notes.** Voice Live's bidirectional
  media streaming is reserved for future multi-turn clarification work and is
  not implemented in this MVP. See DD-01 in
  [.copilot-tracking/plans/logs/2026-09-15/ask-my-human-tight-mvp-log.md](.copilot-tracking/plans/logs/2026-09-15/ask-my-human-tight-mvp-log.md).
* Microsoft Entra ID authenticates calling agents; ACS callbacks are
  separately authenticated by validating the ACS-issued callback JWT.
* Azure Monitor / Application Insights collects content-free OpenTelemetry traces
  and metrics; no prompts, answers, or phone numbers are recorded in
  telemetry.

### Request Flow

```text
Agent -> POST /v1/requests (or MCP tool "ask_human")
  -> AskMyHuman places one ACS call to MY_MOBILE_NUMBER
  -> Human responds by phone (approve/reject or spoken answer)
  -> ACS callback delivers the outcome
  -> AskMyHuman returns a terminal result on the open request
```

The supported deployment policy uses a non-extendable 210-second deadline
starting when the pending row is committed, with new media work stopped at
205 seconds. These are configurable defaults, not an invariant enforced for
every configuration. Preserve this policy beneath the 240-second Container
Apps ingress timeout and configure clients for at least 225 seconds.

Deadline expiry produces `status: "expired"` and `outcome: "deadline_exceeded"`:
an HTTP 200 terminal result and a successful MCP tool result, not an execution
error. A cancelled or closed connection can prevent delivery; persistence of a
terminal result does not guarantee that the initiating client receives it.

## Interfaces

### HTTP API

* `POST /v1/requests`: submit an `AskHumanRequest` and receive an
  `AskHumanResult` (or an `ExecutionError`) once the call reaches a terminal
  state.
* `POST /v1/callbacks/acs`: ACS Call Automation event callback endpoint,
  authenticated with the ACS callback JWT.
* `GET /health/live`: liveness probe.
* `GET /health/ready`: readiness probe (checks the database pool).
* `GET /.well-known/oauth-protected-resource`: OAuth protected-resource
  metadata for MCP clients.

Example JSON body for `POST /v1/requests`:

```json
{
  "kind": "approval",
  "prompt": "Deploy build 482 to production?",
  "idempotencyKey": "5b1b3b7a-8c9e-4c39-9c7e-8b6b6b6b6b6b"
}
```

Example terminal result:

```json
{
  "requestId": "5b1b3b7a-8c9e-4c39-9c7e-8b6b6b6b6b6b",
  "status": "responded",
  "outcome": "approved"
}
```

`kind` is either `approval` or `input`. Terminal `outcome` values are
`approved`, `rejected`, or `answered` (with an `answer` field) for a completed
call, and `no_answer`, `busy`, `declined`, `disconnected`, `cancelled`, or
`deadline_exceeded` when the call did not complete.

Idempotency keys are scoped to the authenticated agent subject while the
request record is retained:

* A matching key and normalized payload joins the existing pending wait or
  replays the stored terminal result or technical error, without another call.
* The same key with a different normalized payload returns HTTP 409
  `idempotency_conflict`.
* A distinct request while the single global pending slot is occupied returns
  HTTP 429. A matching join or replay is not a new admission.

Joining does not reset the original deadline. Validation, authorization,
conflict, admission, dependency, and internal failures use execution errors;
human availability and deadline outcomes use terminal results. No asynchronous
retrieval or resume endpoint is provided.

### MCP

The same capability is exposed over MCP Streamable HTTP, mounted at `/mcp`,
with one `ask_human` tool that accepts the same request shape and returns the
same terminal result shape as the HTTP API.

The authorized calling application needs the `AskHuman.Invoke` application
role and an entry in `AUTHORIZED_AGENT_APP_IDS`. Before release, verify the
actual MCP client supports a timeout of at least 225 seconds and propagates
cancellation. Progress events must not extend the service deadline. Initiating
client cancellation targets `expired/cancelled`; cancelling a joined waiter
must not cancel the creator's request. Record target-client evidence, not only
a configured timeout value or local adapter tests.

## Local Setup

Requirements: Python 3.12, [uv](https://docs.astral.sh/uv/), Docker (for
Postgres/testcontainers and image builds), and the Azure CLI with the Bicep
extension (for infrastructure validation only).

```bash
uv sync --frozen --all-groups
cp .env.example .env
```

For a host process, populate the ignored local environment file privately;
`Settings` reads it relative to the working directory. Copying
[.env.example](.env.example) is only a starting point, not a complete live
configuration. Never commit populated values.

[compose.yaml](compose.yaml) sets literal placeholder Azure values and
throwaway database credentials. It does not bind the host environment file
through `env_file`; editing that file does not configure the app container.
Published ports are loopback-only. Compose is a startup and health smoke setup,
not a fake-call mode or a working live Azure deployment. Do not submit phone
requests with this configuration.

The following Compose procedure is separate from the automated container test;
a successful image build alone does not prove migrations and health:

```bash
docker compose --env-file /dev/null up --build
curl http://localhost:8000/health/live
curl http://localhost:8000/health/ready
```

Run the test suite (spins up a Postgres testcontainer for integration tests):

```bash
uv run pytest -m "not live" --cov=ask_my_human --cov-report=term-missing --cov-fail-under=90
```

The [tests/e2e/test_live_call.py](tests/e2e/test_live_call.py) module is marked `live` and is skipped by
default; it requires a deployed service and real Azure/ACS credentials.

## Configuration

Service configuration is read into a typed `Settings` object. The telemetry
bootstrap separately reads `APPLICATIONINSIGHTS_CONNECTION_STRING` from the
process environment; do not assume the settings file loads that variable into
the process environment.

The callback settings below describe the required corrected contract. Review
repairs are ongoing: confirm source, Compose, and deployment bindings all use
the split before running them. A callback URL is not a JWT audience.

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | PostgreSQL connection string. |
| `ACS_ENDPOINT` | Azure Communication Services resource endpoint. |
| `ACS_SOURCE_PHONE_NUMBER` | Outbound-enabled ACS phone number, E.164 format. |
| `MY_MOBILE_NUMBER` | The one human's phone number, E.164 format. |
| `AZURE_AI_ENDPOINT` | Azure AI Speech endpoint used for Play and Recognize. |
| `ACS_CALLBACK_URL` | Public HTTPS callback URL including the full `/v1/callbacks/acs` endpoint. |
| `ACS_CALLBACK_AUDIENCE` | Immutable ACS resource ID string used for JWT audience validation, not the callback URL. |
| `ENTRA_TENANT_ID` | Microsoft Entra tenant ID used to validate agent tokens. |
| `ENTRA_CLIENT_ID` | Microsoft Entra application (client) ID for this service. |
| `AUTHORIZED_AGENT_APP_IDS` | Comma-separated list of Entra application IDs authorized to call the service. |
| `MCP_ALLOWED_HOSTS` | Comma-separated list of hosts allowed to reach the MCP transport. |
| `LOCALE`, `VOICE_NAME` | Optional overrides for the ACS call locale and voice. |
| `DEADLINE_SECONDS`, `WORK_CUTOFF_SECONDS`, `POLL_INTERVAL_MILLISECONDS`, `RETENTION_HOURS` | Optional overrides for the call deadline, internal work cutoff, poll interval, and database retention window. |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | Optional; when unset, Azure Monitor exporting is skipped so local/test environments start without an Application Insights resource. |

Keep secrets and tenant-specific values out of committed files and retained
command output. [.env.example](.env.example) and [compose.yaml](compose.yaml)
are placeholder templates, not deployment credentials.

## Validation Commands

The required local merge gate, to run from a clean checkout:

```bash
uv lock --check
uv sync --frozen --all-groups
uv run python scripts/export_schemas.py --check
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest -m "not live" --cov=ask_my_human --cov-report=term-missing --cov-fail-under=90
docker compose --env-file /dev/null config --quiet
docker build --tag ask-my-human:mvp .
az bicep build --file infra/main.bicep
```

Rerun the complete gate after documentation edits (Step 4.3) and after final
release corrections (Step 6.1). No repository Markdown command is configured;
use editor diagnostics for changed Markdown and the whitespace fallback:

```bash
git diff --check -- README.md .copilot-tracking/changes/2026-09-15/ask-my-human-tight-mvp-changes.md
```

Record the reviewed revision, actual command results, and each blocker owner
and next action in the review log. The commands above remain required for each
release; see the dated review log for actual results. The non-live
suite now builds and starts the application image against disposable PostgreSQL,
checks migration-before-Uvicorn startup with an encoded password, exercises
liveness/readiness and authentication rejection, and checks query-log redaction.
It uses synthetic settings without mounting the workspace environment file.
Run that bounded test again for the final state; it does not verify Azure ingress.

Local validation is separate from the externally gated Azure and paid-call
procedures below. Under user-approved decision DD-06 (2026-09-16), Phase 4
command evidence covers local validation. Deployment and live procedures remain
mandatory Phase 5 and 6 acceptance gates; documenting them does not count as
executing them.

## Azure Prerequisites And Deployment

Deployment is gated on tenant-specific inputs that cannot be derived from this
repository:

* An existing ACS resource that already owns an outbound-enabled phone number
  (number acquisition is out of scope).
* A Microsoft Entra tenant with application registrations for both this
  service and the authorized calling agent(s), including `AskHuman.Invoke`
  application-role assignment and the configured authorized-client allowlist.
* A target Azure subscription, region, resource group, and container
  registry.
* Approval of the default 24-hour database retention and 30-day content-free
  telemetry retention, or an explicit configuration change.
* Acceptance evidence from the chosen MCP client for at least a 225-second
  timeout and cancellation propagation.
* A public HTTPS callback endpoint and the distinct immutable ACS resource ID
  audience, with consistent settings and deployment bindings.

[scripts/deploy_azure.sh](scripts/deploy_azure.sh) provides deployment assistance,
not completion of all release gates. Its default action is help. Use `what-if`
for a sanitized review, obtain a bound external approval, then explicitly
`publish`. Review the resulting digest with `what-if` and obtain a new approval
before `deploy`. `verify` requires release approval and authenticated health
checks. `rollback` requires a previously approved digest and new mutation
approval; it never rebuilds. Successful script execution is not operator approval.

Supply deployment inputs privately through environment variables, never as
committed parameter literals. Reconcile the current helper's requirements with:
`AZURE_RESOURCE_GROUP`, `AZURE_LOCATION`, `CONTAINER_REGISTRY_NAME`,
`CONTAINER_REGISTRY_SERVER`, `CONTAINER_REGISTRY_RESOURCE_ID`,
`POSTGRES_ADMIN_PASSWORD`, `MY_MOBILE_NUMBER`, `ACS_SOURCE_PHONE_NUMBER`,
`ENTRA_TENANT_ID`, `ENTRA_CLIENT_ID`, `ENTRA_CLIENT_SECRET`,
`AUTHORIZED_AGENT_APP_IDS`, `EXISTING_ACS_RESOURCE_ID`, `ACS_CALLBACK_URL`,
`ACS_CALLBACK_AUDIENCE`, and `MCP_ALLOWED_HOSTS`. Verification may additionally
need an explicit app, expected image digest/revision, and an authenticated
health-check identity. Consult the reviewed helper rather than assuming
verification needs only a resource-group name.

### Operator Release Gates

1. Resolve DR-01 through DR-05. Obtain explicit
  approval for Azure mutations, retention, and separately for paid calls.
2. Inspect the complete what-if change list for the intended one-app
  architecture. A successful exit code is not evidence of a reviewed diff.
  Retain only sanitized evidence, excluding secrets and phone numbers.
3. Build the reviewed source and retain its full Git SHA tag for traceability.
  Tags can be overwritten; record the registry digest and exact deployed
  revision to establish immutable identity. Do not claim a SHA tag alone
  makes an image immutable.
4. Verify the intended revision uses the expected immutable image, is active,
  and reports healthy/running probe state. Verify both liveness and database
  readiness using authenticated external health requests where Entra applies;
  do not relax authentication to make smoke checks succeed.
5. Verify unauthenticated `/v1/requests` and `/mcp` requests and invalid-token
  ACS callbacks are rejected. Do not place an authenticated phone request as
  a health check. Deployment assistance must not automatically run paid calls.
6. Record sanitized revision, digest, probe, authentication, and approval
  evidence before separately authorizing the live matrix.

### Failure And Rollback

Stop before live testing if build, deployment, readiness, or authentication
checks fail. Capture sanitized deployment operations and Container Apps system
logs, with a blocker owner and next action. For an update, use the approved
rollback procedure to redeploy the recorded last-known-good immutable image
and configuration, then repeat revision and health/authentication checks.
Confirm database migration compatibility before rollback; changing an image
does not undo a migration.

For a first deployment with no known-good target, mark release blocked. Retain
failed resources only for bounded diagnosis or remove them through the approved
resource-group process. Do not invent a rollback target or silently proceed to
billable calls.

### Live Call Validation

Live tests place real phone calls and cost money. They stay out of the default
selection behind the `live` marker and `RUN_LIVE_AZURE_TESTS=1`. The following
procedure requires separate operator approval and a verified immutable revision;
it is not part of local validation and has not been run by this documentation
repair:

```bash
RUN_LIVE_AZURE_TESTS=1 uv run pytest -m live tests/e2e/test_live_call.py -vv
```

They additionally require `LIVE_BASE_URL`, `LIVE_API_SCOPE`,
`LIVE_AGENT_TENANT_ID`, `LIVE_AGENT_CLIENT_ID`, `LIVE_AGENT_CLIENT_SECRET`,
and `DATABASE_URL`. `LIVE_APPROVAL_JSON` supplies approved scenarios, isolated
database binding, retention, provider-evidence and telemetry inputs;
`LIVE_DEPLOYMENT_EVIDENCE_JSON` consumes the helper's successful `verify` output.
These JSON values are validated against the evidence models in
[tests/e2e/test_live_call.py](tests/e2e/test_live_call.py). Missing, stale, or
mismatched evidence blocks calls. Each test docstring specifies the scenario
setup; privacy checks also require the configured sensitive sentinel inputs.

The harness is implemented but live acceptance has not been executed. Release evidence must distinguish
approval, rejection, a nonblank spoken answer, initial silence, no answer,
carrier-exposed busy/decline, disconnect, initiating-client cancellation,
forced deadline, join/replay, and authenticated duplicate callbacks. HTTP
coverage alone does not prove live MCP timeout or cancellation behavior.
Database row uniqueness alone does not prove one provider call attempt.

Also require provider-side correlation, one terminal row, accelerated retention
through the production purge path, and live telemetry sentinel absence for
prompts, answers, phone numbers, idempotency keys, tokens, and callback bodies.
Ensure required query dependencies are available and allow bounded telemetry
ingestion time; skipped evidence is not a passing gate. Record carrier limits
as explicitly approved external limitations, not successful scenarios. Final
checks and remaining blockers belong in the review log.

Azure resources use public service endpoints (no VNet) protected by TLS,
managed identity, and application-level authentication; see decision DD-05 in
[.copilot-tracking/plans/logs/2026-09-15/ask-my-human-tight-mvp-log.md](.copilot-tracking/plans/logs/2026-09-15/ask-my-human-tight-mvp-log.md)
for the rationale.
