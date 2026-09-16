
Human-in-the-Loop for Autonomous Agents
Goal: Give autonomous agents a universal way to reach a human when they need help.
PoC Functional Requirements

1. Request: Agent requests either approval or input. Probably through an MCP tool
2. Route: Request goes to the agent’s designated human/owner. Future: multiple humans and roles. For the MVP we just have an env var in the app with MY_MOBILE_NUMBER.
3. Reach: Contact the human via phone call, simplest for MVP.
4. Context: Provide enough context for the human to understand the request and make a decision. This is for the app implementation detail.
5. Response: Support Approve / Reject for approvals and a human-provided answer for input. Voice based , we use gpt-realtime like LLM.
6. Status: Track requests as Pending → Responded / Expired. 
7. Resume: Since we move forward with phone calls only- this is a synchronous operation. no resume capability for the MVP.
8. Escalation: Out of scope for MVP. Future: retries, additional channels, humans/roles, and escalation paths. 
PoC Flow:
Agent → AskHuman → Human → Response → Agent resumes

Minimal PoC Azure stack

- Azure Container Apps: AskHuman API / MCP + orchestration 
- Azure Database for PostgreSQL: Requests, state, responses 
- Azure Communication Services: Phone call / telephony 
- Microsoft Foundry + Voice Live API: Conversational voice AI. 
- Application Insights: Observability


## Run it locally

```bash
uv sync --frozen --all-groups
uv run pytest -m "not live"
docker compose up --build
```

Compose starts PostgreSQL 16 and the service image. The container runs
`alembic upgrade head` against `DATABASE_URL` and then serves Uvicorn on port
8000 with these routes:

| Route | Purpose |
|---|---|
| `POST /v1/requests` | Synchronous ask-human request for an authenticated agent |
| `POST /v1/callbacks/acs` | ACS Call Automation callbacks, authenticated by the ACS token |
| `POST /mcp` | MCP Streamable HTTP transport exposing the single `ask_human` tool |
| `GET /health/live`, `GET /health/ready` | Container Apps probes |
| `GET /.well-known/oauth-protected-resource` | Entra protected-resource metadata |

## Deploy to Azure

Deployment needs an existing subscription, resource group, Azure Container
Registry, an ACS resource that already owns an outbound-enabled number, and the
Microsoft Entra registrations used by Container Apps authentication. Export
every input as an environment variable, never as a committed parameter literal:

`AZURE_RESOURCE_GROUP`, `AZURE_LOCATION`, `CONTAINER_REGISTRY_NAME`,
`CONTAINER_REGISTRY_SERVER`, `CONTAINER_REGISTRY_RESOURCE_ID`,
`POSTGRES_ADMIN_PASSWORD`, `MY_MOBILE_NUMBER`, `ACS_SOURCE_PHONE_NUMBER`,
`ENTRA_TENANT_ID`, `ENTRA_CLIENT_ID`, `ENTRA_CLIENT_SECRET`,
`AUTHORIZED_AGENT_APP_IDS`, `EXISTING_ACS_RESOURCE_ID`, `ACS_CALLBACK_AUDIENCE`,
and `MCP_ALLOWED_HOSTS`.

```bash
scripts/deploy_azure.sh what-if   # Review the change list only
scripts/deploy_azure.sh deploy    # what-if, ACR build, Bicep deploy, revision and auth checks
scripts/deploy_azure.sh verify    # Re-verify the deployed revision later
```

`deploy` tags the image with the full Git commit SHA, so every revision is
immutable and traceable. It fails before any paid phone call when the ready
revision does not run that exact image, when probes are unhealthy, or when
`/v1/requests`, `/mcp`, or the ACS callback accept an unauthenticated caller.

## Live call validation

Live tests place real phone calls and cost money. They stay out of the default
selection behind the `live` marker and `RUN_LIVE_AZURE_TESTS=1`:

```bash
RUN_LIVE_AZURE_TESTS=1 uv run pytest -m live tests/e2e/test_live_call.py -vv
```

They additionally require `LIVE_BASE_URL`, `LIVE_API_SCOPE`,
`LIVE_AGENT_TENANT_ID`, `LIVE_AGENT_CLIENT_ID`, `LIVE_AGENT_CLIENT_SECRET`,
`DATABASE_URL`, and `LIVE_LOG_ANALYTICS_WORKSPACE_ID`. Each test docstring says
whether to answer the phone or let it ring.

## Scope

The MVP places one outbound call per request through ACS Play and Recognize
rather than a Voice Live media relay: one bounded spoken interaction satisfies
both approval and free-form answers with far less moving infrastructure. There
is no resume, escalation, retry, extra channel, second human, or second replica.
