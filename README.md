# AskMyHuman

Human-in-the-loop for autonomous agents. AskMyHuman lets an authenticated agent
place one synchronous request — an approval or a free-form question — that is
answered by a human over a single phone call, and returns a terminal result to
the agent in the same request/response turn.

## Product Scope (Tight MVP)

1. **Request** — An agent asks for either an `approval` or an `input` (free-form
   answer) through an MCP tool or the HTTP API.
2. **Route** — Every request goes to the one human configured through the
   `MY_MOBILE_NUMBER` setting. There is no support for multiple humans, roles,
   or per-agent routing.
3. **Reach** — The service places one outbound phone call through Azure
   Communication Services (ACS).
4. **Context** — The call plays the request's prompt so the human has enough
   context to decide or answer.
5. **Response** — Approvals are captured as approve/reject choices; input
   requests capture one spoken answer transcribed to text.
6. **Status** — Requests move through `pending` → `responded` / `expired` and
   never resume once terminal.
7. **Resume** — Not supported. The call is a synchronous operation bounded by a
   fixed deadline; there is no way to reconnect to a request after the HTTP/MCP
   call returns.
8. **Escalation** — Out of scope. No retries, no additional channels, no
   multiple humans/roles, and no escalation paths.

### Explicit Exclusions

* Multiple humans, roles, or per-agent routing.
* Retries, escalation, or additional notification channels (SMS, email, chat).
* Resuming or reattaching to a request after the synchronous call completes.
* Multi-turn conversation, clarification loops, or free-form voice dialogue.
* Horizontal scaling: the Container Apps deployment is fixed to exactly one
  replica (minimum and maximum) for this MVP.
* Private networking (VNet integration): Azure resources use public service
  endpoints protected by TLS, managed identity, and application-level
  authentication instead of a VNet.

Follow-on ideas (multiple humans, escalation, retries, multi-turn voice,
horizontal scaling, private networking) are tracked in
`.copilot-tracking/plans/logs/2026-09-15/ask-my-human-tight-mvp-log.md` and are
**not** implemented here.

## Architecture

* **Azure Container Apps** — hosts the AskMyHuman API, MCP adapter, and
  orchestration logic as a single FastAPI/Uvicorn ASGI application, fixed to
  one replica.
* **Azure Database for PostgreSQL** — durable storage for request state,
  idempotency, and terminal results, accessed with Psycopg 3 async pooling and
  Alembic migrations.
* **Azure Communication Services (ACS) Call Automation** — places the one
  outbound phone call per request and drives the call through callbacks.
* **ACS Play and Recognize with Azure AI Speech** — captures the human's
  approve/reject choice or spoken free-form answer using one bounded
  choice/speech-recognition action. **This replaces the Microsoft Foundry
  Voice Live API named in earlier product notes.** Voice Live's bidirectional
  media streaming is reserved for future multi-turn clarification work and is
  not implemented in this MVP (see decision DD-01 in the planning log).
* **Microsoft Entra ID** — authenticates calling agents; ACS callbacks are
  separately authenticated by validating the ACS-issued callback JWT.
* **Azure Monitor / Application Insights** — content-free OpenTelemetry traces
  and metrics; no prompts, answers, or phone numbers are recorded in
  telemetry.

### Request Flow

```
Agent → POST /v1/requests (or MCP tool "ask_human")
      → AskMyHuman places one ACS call to MY_MOBILE_NUMBER
      → Human responds by phone (approve/reject or spoken answer)
      → ACS callback delivers the outcome
      → AskMyHuman returns a terminal result to the agent in the same call
```

The entire round trip is bounded by a **210-second deadline**, comfortably
inside the 240-second Azure Container Apps ingress timeout, so the agent
always receives a terminal result (or a `deadline_exceeded` execution error)
before the platform would otherwise close the connection.

## Interfaces

### HTTP API

* `POST /v1/requests` — submit an `AskHumanRequest` and receive an
  `AskHumanResult` (or an `ExecutionError`) once the call reaches a terminal
  state.
* `POST /v1/callbacks/acs` — ACS Call Automation event callback endpoint,
  authenticated with the ACS callback JWT.
* `GET /health/live` — liveness probe.
* `GET /health/ready` — readiness probe (checks the database pool).
* `GET /.well-known/oauth-protected-resource` — OAuth protected-resource
  metadata for MCP clients.

Example request:

```json
POST /v1/requests
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

### MCP

The same capability is exposed over MCP Streamable HTTP, mounted at `/mcp`,
with one `ask_human` tool that accepts the same request shape and returns the
same terminal result shape as the HTTP API.

## Local Setup

Requirements: Python 3.12, [uv](https://docs.astral.sh/uv/), Docker (for
Postgres/testcontainers and image builds), and the Azure CLI with the Bicep
extension (for infrastructure validation only).

```bash
uv sync --frozen --all-groups
cp .env.example .env   # then fill in real values for a live Azure environment
```

Run the service locally with Docker Compose (throwaway local credentials,
placeholder Azure values, no real Azure calls are made):

```bash
docker compose up --build
curl http://localhost:8000/health/live
curl http://localhost:8000/health/ready
```

Run the test suite (spins up a Postgres testcontainer for integration tests):

```bash
uv run pytest -m "not live" --cov=ask_my_human --cov-report=term-missing --cov-fail-under=90
```

The `tests/e2e/test_live_call.py` module is marked `live` and is skipped by
default; it requires a deployed service and real Azure/ACS credentials.

## Configuration

All configuration is read from environment variables (see `.env.example`) into
a single typed `Settings` object:

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | PostgreSQL connection string. |
| `ACS_ENDPOINT` | Azure Communication Services resource endpoint. |
| `ACS_SOURCE_PHONE_NUMBER` | Outbound-enabled ACS phone number, E.164 format. |
| `MY_MOBILE_NUMBER` | The one human's phone number, E.164 format. |
| `AZURE_AI_ENDPOINT` | Azure AI Speech endpoint used for Play and Recognize. |
| `ACS_CALLBACK_AUDIENCE` | Public base URL ACS uses for callbacks and JWT audience validation. |
| `ENTRA_TENANT_ID` | Microsoft Entra tenant ID used to validate agent tokens. |
| `ENTRA_CLIENT_ID` | Microsoft Entra application (client) ID for this service. |
| `AUTHORIZED_AGENT_APP_IDS` | Comma-separated list of Entra application IDs authorized to call the service. |
| `MCP_ALLOWED_HOSTS` | Comma-separated list of hosts allowed to reach the MCP transport. |
| `LOCALE`, `VOICE_NAME` | Optional overrides for the ACS call locale and voice. |
| `DEADLINE_SECONDS`, `WORK_CUTOFF_SECONDS`, `POLL_INTERVAL_MILLISECONDS`, `RETENTION_HOURS` | Optional overrides for the call deadline, internal work cutoff, poll interval, and database retention window. |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | Optional; when unset, Azure Monitor exporting is skipped so local/test environments start without an Application Insights resource. |

No secret value or tenant-specific identifier is committed to this repository;
`.env.example` and `compose.yaml` only contain placeholders.

## Validation Commands

The full local merge gate, run from a clean checkout:

```bash
uv lock --check
uv sync --frozen --all-groups
uv run python scripts/export_schemas.py --check
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest -m "not live" --cov=ask_my_human --cov-report=term-missing --cov-fail-under=90
docker compose config --quiet
docker build --tag ask-my-human:mvp .
az bicep build --file infra/main.bicep
```

## Azure Prerequisites And Deployment

Deployment is gated on tenant-specific inputs that cannot be derived from this
repository:

* An existing ACS resource that already owns an outbound-enabled phone number
  (number acquisition is out of scope).
* A Microsoft Entra tenant with application registrations for both this
  service and the authorized calling agent(s).
* A target Azure subscription, region, resource group, and container
  registry.
* Approval of the default 24-hour database retention and 30-day content-free
  telemetry retention, or an explicit configuration change.

Given those inputs, deployment uses the Bicep templates in `infra/`:

```bash
az bicep build --file infra/main.bicep
az deployment group what-if --resource-group <rg> --template-file infra/main.bicep --parameters <params-file>
az deployment group create --resource-group <rg> --template-file infra/main.bicep --parameters <params-file>
```

Azure resources use public service endpoints (no VNet) protected by TLS,
managed identity, and application-level authentication; see decision DD-05 in
the planning log for the rationale.
