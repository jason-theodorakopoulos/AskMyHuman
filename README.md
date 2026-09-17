---
title: AskMyHuman
description: Synchronous human approval and spoken answers for authenticated AI agents.
---

## Human judgment, one call away

AI agents can act independently, but some decisions still need human judgment.
AskMyHuman gives an authenticated agent a direct way to request that judgment:
the agent submits an approval request or a free-form question, selects a phone
number, and the service calls that person through Azure Communication Services
(ACS). The answer returns to the agent in the same request.

The phone call is the bridge because it is one of the most universal interfaces
available. There is no new app to install, account to create, or dashboard to
monitor. A person can respond from a familiar device wherever they are, without
learning another workflow. The call explains the context and lets them approve,
reject, or provide a spoken answer, keeping the agent moving while the human
stays in control.

Behind that familiar interaction, AskMyHuman provides a native MCP tool and a
synchronous API. It manages callbacks, deadlines, duplicate requests, and
response states, turning human judgment into one dependable, structured result
the agent can act on. Use it for decisions such as approving a deployment,
confirming a sensitive action, or answering a question that requires human
context.

## How it works

1. An agent calls the `ask_human` MCP tool or sends `POST /v1/requests`.
2. The request supplies the human destination as an E.164 `phoneNumber`.
3. AskMyHuman persists the destination and places one outbound ACS call.
4. ACS reads the prompt using Azure AI Speech.
5. The human approves, rejects, or speaks an answer.
6. ACS recognizes the response and sends it to AskMyHuman by callback.
7. The agent receives the terminal result on the open request.

```text
Agent -> AskMyHuman -> ACS phone call -> Human
Agent <- AskMyHuman <- ACS callback  <- Human response
```

## Product capabilities

* Approval requests with voice or keypad responses
* Free-form questions with speech-to-text answers
* MCP Streamable HTTP and REST interfaces
* Microsoft Entra ID authentication and application-role authorization
* Durable request state, destination, and idempotent replay with PostgreSQL
* Content-free OpenTelemetry traces and metrics
* A fixed 210-second request deadline by default

The current release supports one caller-selected human, one call per request,
and one response. It does not support retries, escalation, calling multiple
recipients in one request, multi-turn conversations, asynchronous retrieval,
or horizontal scaling.

## Interfaces

### MCP

Connect an MCP client to `/mcp` and invoke `ask_human` with the same fields as
the HTTP request below, including the required `phoneNumber`. The calling
application must have the `AskHuman.Invoke` application role, and its application
ID must be listed in `AUTHORIZED_AGENT_APP_IDS`.

Use a client timeout of at least 225 seconds.

### HTTP

Send an authenticated request to `POST /v1/requests`:

```json
{
  "kind": "approval",
  "prompt": "Deploy build 482 to production?",
  "idempotencyKey": "5b1b3b7a-8c9e-4c39-9c7e-8b6b6b6b6b6b",
  "phoneNumber": "+15555550101"
}
```

A completed approval returns:

```json
{
  "requestId": "5b1b3b7a-8c9e-4c39-9c7e-8b6b6b6b6b6b",
  "status": "responded",
  "outcome": "approved"
}
```

Set `kind` to `approval` for an approve/reject choice or `input` for a spoken
answer. Supply `phoneNumber` in strict E.164 form: `+`, a nonzero first digit,
and 2 to 15 total digits. Completed outcomes are `approved`, `rejected`, or
`answered`. Calls that do not complete can return `no_answer`, `busy`, `declined`,
`disconnected`, `cancelled`, or `deadline_exceeded`.

Other endpoints:

* `POST /v1/callbacks/acs` receives authenticated ACS events
* `GET /health/live` reports process health
* `GET /health/ready` reports database and maintenance readiness
* `GET /.well-known/oauth-protected-resource` publishes MCP OAuth metadata

Idempotency keys are scoped to the authenticated agent. Reusing a key with the
same request joins an active wait or replays its result without placing another
call. Reusing it with different content, including another `phoneNumber`,
returns HTTP 409. Because this release
allows one active request globally, another request returns HTTP 429 while the
slot is occupied.

## Local development

Requirements: Python 3.12, [uv](https://docs.astral.sh/uv/), and Docker.

```bash
uv sync --frozen --all-groups
cp .env.example .env
docker compose --env-file /dev/null up --build
```

Check the running service:

```bash
curl http://localhost:8000/health/live
curl http://localhost:8000/health/ready
```

The Compose configuration uses placeholder Azure values and cannot place a
real call. For host-based development, populate the ignored `.env` file with
your own settings. Never commit credentials or phone numbers.

## Configuration

| Variable                                | Purpose                                                              |
|-----------------------------------------|----------------------------------------------------------------------|
| `DATABASE_URL`                          | PostgreSQL connection string                                         |
| `ACS_ENDPOINT`                          | ACS resource endpoint                                                |
| `ACS_SOURCE_PHONE_NUMBER`               | Outbound-enabled ACS number in E.164 format                           |
| `AZURE_AI_ENDPOINT`                     | Azure AI Speech endpoint for playback and recognition                |
| `ACS_CALLBACK_URL`                      | Public HTTPS URL ending in `/v1/callbacks/acs`                        |
| `ACS_CALLBACK_AUDIENCE`                 | Immutable ACS resource ID used to validate callback tokens           |
| `ENTRA_TENANT_ID`                       | Microsoft Entra tenant ID                                            |
| `ENTRA_CLIENT_ID`                       | Service application client ID                                        |
| `AUTHORIZED_AGENT_APP_IDS`              | Comma-separated authorized application IDs                           |
| `MCP_ALLOWED_HOSTS`                     | Comma-separated hosts allowed to reach MCP                            |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | Optional Azure Monitor exporter connection                           |

Optional settings include `LOCALE`, `VOICE_NAME`, `DEADLINE_SECONDS`,
`WORK_CUTOFF_SECONDS`, `POLL_INTERVAL_MILLISECONDS`, and `RETENTION_HOURS`.

## Deploy to Azure

The Bicep templates deploy the Container App, PostgreSQL, Azure AI Services,
managed identities, role assignments, and observability resources. You must
provide:

* An existing ACS resource with a system-assigned identity
* An outbound-enabled ACS phone number
* Microsoft Entra app registrations and the `AskHuman.Invoke` role assignment
* An Azure subscription, resource group, region, and container registry
* A public callback URL and the ACS immutable resource ID audience

Use [scripts/deploy_azure.sh](scripts/deploy_azure.sh) to review, publish,
deploy, verify, or roll back a release. Start with its help and `what-if`
commands. The script never treats deployment as approval to place paid calls.

## Validate

Run the local checks:

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

Live validation places real, billable phone calls and requires a deployed,
verified release plus explicit operator approval:

```bash
RUN_LIVE_AZURE_TESTS=1 uv run pytest -m live tests/e2e/test_live_call.py -vv
```

See [tests/e2e/test_live_call.py](tests/e2e/test_live_call.py) for the required
credentials, deployment evidence, and scenario approvals.

## Architecture

AskMyHuman runs as one FastAPI application on Azure Container Apps. It combines
the MCP and HTTP interfaces, call orchestration, ACS callbacks, and maintenance
work in a single replica. PostgreSQL stores request state and terminal results.
It also stores the caller-selected destination so callbacks after a restart use
the same human. ACS Call Automation and Azure AI Speech provide calling,
text-to-speech, and speech recognition. Azure Monitor receives content-free
operational telemetry.

Azure resources use public TLS endpoints protected by managed identity and
application-level authentication. Prompts, answers, phone numbers, and tokens
are excluded from telemetry.
