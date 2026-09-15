---
title: AskMyHuman Repository Scope Research
description: Verified implementation-relevant repository facts and tight MVP scope guidance
author: GitHub Copilot
ms.date: 2026-09-15
ms.topic: reference
---

## Research Questions

* What is the current project maturity?
* Which implementation conventions already exist?
* What does the repository explicitly require for the proof of concept and MVP?
* Which repository, product, operational, and licensing constraints affect implementation?
* What should and should not enter the tight MVP?

## Current Status

Complete as of 2026-09-15. The committed tree, full visible workspace,
repository instructions, license, Git configuration, refs, status, and commit
history were inspected. External Azure capability verification remains assigned
to separate research artifacts and is not treated as established here.

## Repository Maturity

The repository is a product brief at pre-implementation maturity.

* `HEAD` tracks exactly .gitignore, LICENSE, and README.md. There are no source
  files, dependency manifests, tests, schemas, deployment definitions, CI
  workflows, or application configuration examples.
* Git history contains three commits: c76a2fa added .gitignore and LICENSE,
  b77ff35 added README.md, and 3bf9a68 revised only the README requirements.
  All three commits were made between 2026-09-14 and 2026-09-15.
* The latest README commit deliberately replaced SMS-or-phone reach and
  asynchronous resume with a phone-only, single-owner, synchronous MVP. This
  is a strong scope decision, not an accidental omission.
* The active branch is main, and local main and packed origin/main both point
  to 3bf9a6894d4607f56aaf4b45d0f9bd27e8174990. No additional local or packed
  remote branch is present.
* .copilot-tracking is untracked. Its other research files are planning inputs,
  not shipped implementation or accepted architecture. The principal scope
  draft still marks code search, external research, standards, architecture,
  and implementation details as pending.
* No AGENTS.md, .github/copilot-instructions.md, copilot-instructions.md, or
  repository-local `*.instructions.md` file exists. No additional repository
  convention overrides were found.

## Existing Conventions and Decisions

Only a small number of conventions are established.

* The project uses the MIT License. Redistribution of substantial portions must
  retain the copyright and permission notice, and the software is provided
  without warranty.
* .gitignore is the standard broad Python template. It covers Python bytecode,
  packaging, test output, virtual environments, type-checker caches, Ruff, and
  several Python frameworks. This is evidence of probable Python intent, but it
  does not select a Python version, package manager, framework, formatter, test
  runner, or type checker.
* Runtime destination configuration is named `MY_MOBILE_NUMBER` and is expected
  to come from an environment variable.
* Azure is the stated deployment platform. The named stack is Azure Container
  Apps, Azure Database for PostgreSQL, Azure Communication Services, Microsoft
  Foundry with Voice Live API, and Application Insights.
* The agent interface is not finalized. The README says the request will
  "probably" use an MCP tool, so MCP is a preferred direction rather than a
  settled protocol requirement.
* Naming is inconsistent: the repository and title use AskMyHuman, while the
  flow uses AskHuman. One product and package name should be selected before
  implementation.

## Explicit MVP Requirements

The tight MVP must preserve these behaviors.

1. An autonomous agent submits either an approval request or a free-form input
   request.
2. Every request routes to one designated owner whose mobile number is supplied
   through `MY_MOBILE_NUMBER`.
3. The only human channel is one outbound phone call.
4. The call communicates enough request context for the owner to decide or
   answer.
5. Approval requests return approve or reject. Input requests return the
   human's spoken answer.
6. Request state is limited to pending, responded, or expired.
7. The agent-facing operation is synchronous. The waiting invocation receives
   the response or terminal expiry; there is no later resume capability.
8. The intended proof-of-concept flow is agent to AskHuman, human, response,
   then resumed agent execution.
9. Retries, escalation, additional channels, multiple humans, and roles are
   explicitly excluded.

The repository does not define request fields, response fields, error codes,
timeouts, expiry semantics, authentication, authorization, idempotency,
retention, deployment region, model selection, or acceptance tests.

## Derived Constraints

These constraints follow from the committed requirements but are not themselves
specified contracts.

* Synchronous completion plus an expired terminal state requires one explicit,
  bounded end-to-end deadline. The behavior for no answer, abandoned calls,
  client disconnects, and late voice responses must map deterministically to
  that deadline.
* A synchronous agent contract does not require the internal call lifecycle to
  be implemented as one blocking procedure. Internal call events still need a
  correlation identifier and a state transition that resolves the waiting
  invocation once.
* PostgreSQL remains in the named minimal stack even though resume is excluded.
  Its tight-MVP purpose should be restricted to request correlation, terminal
  state, response recording, and diagnostic durability. It should not become a
  workflow or routing system.
* `MY_MOBILE_NUMBER`, spoken context, transcripts or extracted answers, and
  approval decisions are sensitive data. Secrets management, access control,
  log redaction, retention, and deletion behavior are implementation blockers
  even though the README is silent about them.
* The broad goal of a "universal" human-help mechanism conflicts with the
  deliberately Azure-specific proof of concept. Universality should stop at a
  small stable agent contract; provider abstraction is not required to prove
  the MVP.
* README.md names both a "gpt-realtime like LLM" and Microsoft Foundry Voice
  Live API. The exact voice service, model, SDK, and integration mode must be
  selected before dependencies or architecture are committed.

## Evidence

### Product Brief

* README.md:2-4 names the product goal and identifies the content as proof-of-
  concept functional requirements.
* README.md:6-10 defines the two request modes, probable MCP entry point,
  single-owner environment configuration, phone-only contact, required context,
  and voice response behavior.
* README.md:11-13 defines the three states, synchronous operation, no resume,
  and explicit exclusions.
* README.md:14-15 gives the complete intended proof-of-concept flow.
* README.md:17-23 names the minimal Azure stack.

### Repository and Legal Metadata

* LICENSE:1-3 identifies the MIT License and copyright holder.
* LICENSE:5-13 grants use and redistribution rights and requires preservation of
  the notice.
* LICENSE:15-21 contains the warranty and liability disclaimer.
* .gitignore:1-52 covers Python bytecode, packaging, and test artifacts.
* .gitignore:85-128 covers Python environment and package-manager conventions
  without selecting one.
* .gitignore:150-158 excludes environment files and common virtual environments.
* .gitignore:170-179 and .gitignore:206-207 cover Python type-checker and Ruff
  caches.
* .git/HEAD:1-1 selects refs/heads/main.
* .git/config:1-13 identifies a non-bare repository, the GitHub origin, main
  branch tracking, and Git LFS repository format support.
* .git/packed-refs:1-2 records origin/main at the current commit.
* .git/refs/remotes/origin/HEAD:1-1 selects origin/main as the remote default.
* .git/logs/HEAD:1-1 records the clone of the current GitHub repository.

### Workspace Research State

* .copilot-tracking/research/2026-09-15/tight-mvp-scope-research.md:49-66
  summarizes the README but marks code search, external research, and project
  conventions as pending.
* .copilot-tracking/research/2026-09-15/tight-mvp-scope-research.md:77-119
  leaves implementation patterns, examples, APIs, architecture, and alternatives
  pending.
* .copilot-tracking/research/subagents/2026-09-15/minimal-mvp-architecture-research.md:30-58
  marks every architecture result section as research in progress.
* .copilot-tracking/research/subagents/2026-09-15/azure-voice-telephony-research.md:22-49
  states a relay hypothesis but leaves findings, option evaluation,
  recommendation, gaps, and sources in progress.

## Key Risks

* The synchronous contract can fail unpredictably unless all MCP or HTTP,
  Container Apps, telephony, voice-session, and application deadlines are
  reconciled around one shorter product deadline.
* Missing idempotency and single-resolution rules can place duplicate paid calls
  or produce conflicting terminal responses after callback retries or client
  disconnects.
* An unauthenticated agent-facing call tool would expose a direct cost and abuse
  path. Authentication, authorization, rate limiting, and destination locking
  are MVP safeguards, not future enterprise features.
* Spoken context and answers may contain confidential data. Persisting or
  emitting them through PostgreSQL and Application Insights without a redaction
  and retention policy creates privacy and compliance exposure.
* Voice service terminology is unresolved, and the dedicated telephony research
  has no verified findings yet. The proposed Azure services must not be assumed
  to connect directly until that research is complete.
* The single environment-configured number is intentionally narrow, but a
  leaked, malformed, or unsupported number can make every request fail. Startup
  validation and secret-backed configuration are necessary.
* No executable project convention exists. Premature framework, package manager,
  infrastructure, or schema choices could create avoidable churn.

## Tight MVP Recommendations

### Include

* One authenticated agent endpoint, preferably one MCP tool if the owner
  confirms MCP, with a stable discriminated request for `approval` or `input`.
* One server-generated request identifier, one bounded deadline, one idempotency
  key, and exactly-once terminal resolution from the caller's perspective.
* One destination loaded from secret-backed `MY_MOBILE_NUMBER`, validated at
  startup, with no caller-supplied phone-number override.
* One outbound call attempt through Azure Communication Services and one chosen
  Microsoft voice integration. Resolve the Voice Live versus realtime-model
  wording before implementation.
* The minimum state machine: pending to responded or pending to expired. Store
  only the correlation data and response needed for this flow.
* A thin PostgreSQL record because PostgreSQL is explicitly in the proposed
  minimal stack. Avoid routing, queues, workflow tables, and generalized audit
  models.
* Correlated Application Insights telemetry for request start, call outcome,
  terminal state, duration, and sanitized error category. Exclude phone numbers,
  raw context, and spoken answers from default telemetry.
* Focused contract and state-transition tests plus one real end-to-end call
  demonstration for both approval and free-form input.

### Exclude

* SMS, email, chat, push notifications, inbound calling, and channel selection.
* Multiple humans, roles, routing rules, schedules, delegation, and contact
  management.
* Retries, fallback channels, escalation chains, and human availability logic.
* Asynchronous polling, callbacks to agents, durable resume, inboxes, dashboards,
  and administrative user interfaces.
* Caller-selected destinations, general-purpose telephony APIs, and public
  unauthenticated endpoints.
* Provider-neutral telephony or voice abstractions, plugin systems, event buses,
  and generalized workflow engines.
* Full transcripts, audio retention, analytics, long-term history, and broad
  observability payloads unless a separately approved requirement demands them.
* Production-scale high availability, multi-region deployment, and multi-tenant
  isolation. Basic security, timeout handling, and privacy controls remain in
  scope because the demonstration cannot be credible without them.

## Follow-on Questions

The following implementation research remains outside this repository-only
inspection.

* [ ] Verify the supported Azure Communication Services and Voice Live
  integration path, including whether a custom bidirectional media relay is
  required.
* [ ] Verify audio formats, SDK and API versions, callback behavior,
  authentication, service regions, phone-number availability, and current
  preview or general-availability status.
* [ ] Measure or document MCP client, server transport, Azure Container Apps,
  call setup, and voice-session timeout limits to set the product deadline.
* [ ] Define the smallest request, response, and error schema after confirming
  whether MCP is mandatory.
* [ ] Confirm the minimum PostgreSQL schema and whether the repository owner
  considers PostgreSQL mandatory for the first demonstration.
* [ ] Establish phone-call consent, recording and transcription policy, data
  residency, retention, and deletion requirements for the target region.
* [ ] Select Python version, package manager, web or MCP framework, test runner,
  formatter, linter, type checker, and infrastructure-as-code approach.

## Clarifying Questions

* Is MCP required for the first demonstration, or may the initial agent contract
  be a synchronous HTTP API?
* Is Microsoft Foundry Voice Live API the required voice service, or does
  "gpt-realtime like LLM" permit another Azure-hosted realtime model or API?
* Is Azure Database for PostgreSQL a hard MVP requirement, or may the first live
  demonstration use ephemeral state if terminal results and telemetry remain
  observable?
* What is the maximum acceptable wait from tool invocation to expiry, and how
  should unanswered, busy, rejected, and disconnected calls map to the public
  response?
* Which agents are trusted to invoke calls, and what authentication mechanism is
  available to them?
* Which country or region owns the demonstration phone number, and are call
  recording or transcript retention permitted?
* Should the canonical product and code name be AskMyHuman or AskHuman?