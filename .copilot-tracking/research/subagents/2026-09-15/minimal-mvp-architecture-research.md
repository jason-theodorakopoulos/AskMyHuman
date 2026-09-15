---
title: Minimal MVP Architecture Research
description: Evidence and recommendation for the smallest credible AskMyHuman synchronous voice-call MVP
ms.date: 2026-09-15
ms.topic: architecture
---

## Research questions

* What current MCP server transport supports a synchronous waiting tool call, and what timeout constraints apply?
* What is the smallest useful request and response schema for approval and free-form input?
* Which security and abuse controls are mandatory for an MVP that places outbound calls?
* How do Azure Container Apps request timeouts constrain the end-to-end interaction?
* Which persistence option best balances shipping speed and demo reliability?
* What observability is required to diagnose one request across MCP, telephony, and voice AI?
* Which end-to-end architecture is smallest without making the demo brittle?

## README constraints

* One environment-configured mobile number
* Outbound voice call through Azure Communication Services
* Conversational voice through Microsoft Foundry Voice Live API
* Approval or free-form input
* Pending, responded, and expired states
* Synchronous completion inside the waiting tool call
* No retries, escalation, multiple humans, roles, channels, or resume capability

## Findings

### MCP invocation, transport, and timeout ownership

The MCP `2026-07-28` specification defines `tools/call` as a JSON-RPC request.
For remote servers, Streamable HTTP uses one HTTP `POST` per JSON-RPC message.
The server returns either one `application/json` response or a request-scoped
Server-Sent Events (SSE) stream whose final event is the JSON-RPC response.
Streamable HTTP has no protocol-level session or resumable response stream in
this revision. A synchronous AskMyHuman call can therefore remain one waiting
`tools/call`; progress events are optional and do not make the call resumable.

MCP does not prescribe a universal request duration. The sender should set a
configurable per-request timeout, cancel when it expires, and enforce a maximum
even if progress resets an idle timer. With Streamable HTTP, closing the response
stream is cancellation and the server should stop work promptly. Timeout
ownership is consequently shared: the client owns how long it waits, the
AskMyHuman service owns its business deadline, and every HTTP intermediary can
impose a shorter transport limit.

Azure Container Apps HTTP ingress has a fixed 240-second request timeout. A
phone interaction cannot safely consume all 240 seconds because the service
still needs time to persist a terminal result and serialize the HTTP response.

> [!IMPORTANT]
> **Derived design decision:** Use one 210-second monotonic end-to-end deadline,
> measured from acceptance of a validated request through dialing, conversation,
> persistence, and response serialization. Recommend an MCP client timeout of at
> least 225 seconds. Progress never extends the 210-second service deadline.

## Alternatives

Research in progress.

## Recommended architecture

Research in progress.

## Sequence flow

Research in progress.

## Explicit exclusions

Research in progress.

## Practical implementation steps

Research in progress.

## Sources

Research in progress.

## Gaps and clarifying questions

Research in progress.
