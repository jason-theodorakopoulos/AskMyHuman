
Goal: Give autonomous agents a universal way to reach a human when they need help.
PoC Functional Requirements

1. Request: Agent requests either approval or input. 
2. Route: Request goes to the agent’s designated human/owner. Future: multiple humans and roles. 
3. Reach: Contact the human via SMS or phone call. 
4. Context: Provide enough context for the human to understand the request and make a decision. 
5. Response: Support Approve / Reject for approvals and a human-provided answer for input. 
6. Status: Track requests as Pending → Responded / Expired. 
7. Resume: Store the response and make it available to the agent so it can resume, supporting long-running human waits independent of agent/session/MCP timeouts. 
8. Escalation: Out of scope for PoC. Future: retries, additional channels, humans/roles, and escalation paths. 
PoC Flow:
Agent → AskHuman → Human → Response → Agent resumes

Minimal PoC Azure stack

- Azure Container Apps: AskHuman API / MCP + orchestration 
- Azure Database for PostgreSQL: Requests, state, responses 
- Azure Communication Services: Phone call / telephony 
- Microsoft Foundry + Voice Live API: Conversational voice AI. 
- Application Insights: Observability
