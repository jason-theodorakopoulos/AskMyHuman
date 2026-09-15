
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
