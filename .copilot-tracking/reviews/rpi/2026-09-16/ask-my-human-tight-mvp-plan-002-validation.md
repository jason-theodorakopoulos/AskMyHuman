---
title: Phase 1B Infrastructure Validation
description: Product-code validation of the Ask My Human Phase 1B infrastructure modules.
ms.date: 2026-09-16
---

## Scope and Status

Status: Failed. Validation complete; two Critical product findings remain.

Phase: 1B (002). Review product code only. Preserve the approved public-endpoint decision.
No implementation changes, deployments, Azure login, secret access, or resource creation are authorized.
Only this report was edited. No paid calls, environment-file reads, commits, or tool installations occurred.
Missing external evidence is reported separately and does not determine the product failure status.

## Validation Inputs

Read in full: the supplied implementation plan (285 lines), changes log (168 lines),
primary research (342 lines), details (1,140 lines), and planning log (154 lines).
The controlling scope is Steps 1B.1 through 1B.4, including their success criteria.
Planning decisions DD-04 and DD-05 approve nested cross-scope role-assignment
modules and public service endpoints. DR-01 through DR-05 remain external release gates.

* [Implementation plan](.copilot-tracking/plans/2026-09-15/ask-my-human-tight-mvp-plan.instructions.md#L173): all four Phase 1B checklist entries are marked complete.
* [Implementation details](.copilot-tracking/details/2026-09-15/ask-my-human-tight-mvp-details.md#L598): controlling steps and success criteria.
* [Changes log](.copilot-tracking/changes/2026-09-15/ask-my-human-tight-mvp-changes.md#L124): claimed module implementations and historical validation.
* [Primary research](.copilot-tracking/research/2026-09-15/tight-mvp-scope-research.md#L212): ACS resource audience and 30-day telemetry requirements.
* [Planning log](.copilot-tracking/plans/logs/2026-09-15/ask-my-human-tight-mvp-log.md#L52): approved nested modules and public endpoints.

Links identify workspace-relative files and 1-based source lines. The original report's historical
artifact-read record and build claim are preserved below; neither substitutes for verification in this session.

## Requirement Matrix

| Step | Changes-log match                  | Source assessment                                  | Acceptance limitation                   |
|------|------------------------------------|----------------------------------------------------|-----------------------------------------|
| 1B.1 | Public PostgreSQL and TLS          | Required source settings verified                  | Fresh independent build unavailable     |
| 1B.2 | Identity, AI, ACS and nested RBAC   | Resources and identity wiring verified             | ACS role evidence gate E-01 remains     |
| 1B.3 | Workspace-based 30-day telemetry   | Resources present; effective retention incomplete   | Critical C-02                           |
| 1B.4 | App, auth, probes, secrets and ACR | Resource settings present; callback contract broken | Critical C-01 and live boundary gate     |

### Step 1B.1 Evidence

The [PostgreSQL module](infra/modules/postgresql.bicep#L7) secures the password,
restricts the version to 16, creates Standard_B1ms/Burstable with a 32-GB database server,
and provisions the application database. The [firewall](infra/modules/postgresql.bicep#L52)
uses the Azure-services-specific `0.0.0.0` pair, not an unrestricted internet address range.
[TLS configuration](infra/modules/postgresql.bicep#L61) requires secure transport and TLSv1.2.
[Outputs](infra/modules/postgresql.bicep#L88) contain only identifiers, host, and database name.
No VNet, subnet, private endpoint, or private DNS resource is added. All source criteria match;
independent compilation is a separate evidence gate.

### Step 1B.2 Evidence

The [identity module](infra/modules/identity.bicep#L9) creates one user-assigned identity and
exports its resource, principal, and client IDs. [Communications](infra/modules/communications.bicep#L22)
references the existing cross-scope ACS resource, creates an S0 AIServices account with a custom
subdomain, and assigns Cognitive Services User to the ACS system-assigned principal at AI-resource
scope. It does not acquire or configure a phone number, create ACS, deploy Voice Live, or output
keys, tokens, numbers, or connection strings. The separate
[ACS assignment module](infra/modules/communications-acs-role-assignment.bicep#L15) targets the
Container App principal at ACS-resource scope. Its role identity and permissions require E-01;
compilation alone cannot establish that a literal GUID is a usable role.

### Step 1B.3 Evidence

The [observability module](infra/modules/observability.bicep#L13) creates one PerGB2018 workspace
and one workspace-based Application Insights component, with public ingestion and query access.
Both retention fields are explicitly 30, but they do not configure the Application Insights table
exceptions (C-02). No body capture, raw callback collection, or content-bearing custom properties
are configured. Outputs are resource IDs and the telemetry connection setting required by the frozen
contract. An Application Insights ingestion connection string is not an ACS access key or a query
credential; its output is not independently classified as a secret disclosure.

### Step 1B.4 Evidence

The [Container App module](infra/modules/container-app.bicep#L90) creates a public environment
and one HTTPS external-ingress app on port 8000. It sets Single revision mode, one container,
and [minimum and maximum replicas of one](infra/modules/container-app.bicep#L272).
It attaches the user-assigned identity, configures identity-based image pull, and depends on the
[ACR-scoped AcrPull assignment](infra/modules/container-app-acr-role-assignment.bicep#L14).
Passwords, phone numbers, and telemetry settings use secrets and secret references; the DSN includes
`sslmode=require`. [Runtime settings](infra/modules/container-app.bicep#L220) carry the 210/205-second
limits, 500-ms polling, and 24-hour row retention. Both HTTP probes target container port 8000.

[Authentication](infra/modules/container-app.bicep#L282) enables Entra, returns 401 for unauthenticated
requests, restricts audiences and applications, disables the token store, and excludes only
`/v1/callbacks/acs`. No health or metadata exclusion is proposed. The application still validates
callback JWTs, but its configured audience is incorrect (C-01). Single-revision and replica settings
match the plan; this is not proof that platform rollout mechanics never briefly overlap processes.

## Severity Findings

Critical means missing or incorrect required functionality. Major means a specification deviation
degrading maintainability. Minor means a style or documentation gap.

### C-01 Critical: Callback Audience Is Conflated With Service URL

Requirement: Step 1B.4 must allow genuine ACS callbacks through application JWT validation;
the research requires the configured ACS resource audience.

Evidence: [composition input](infra/main.bicep#L31) describes `acsCallbackAudience` as the public
service URL, and the [app binding](infra/modules/container-app.bicep#L195) forwards it unchanged.
[Settings](src/ask_my_human/config.py#L24) requires `AnyHttpUrl`.
[Gateway construction](src/ask_my_human/telephony/acs_client.py#L47) appends the callback path to it,
while [application composition](src/ask_my_human/main.py#L143) also passes it to the JWT validator.
[JWT decoding](src/ask_my_human/security/acs_callback.py#L83) enforces that audience.

The [Microsoft webhook contract](https://learn.microsoft.com/azure/communication-services/how-tos/call-automation/secure-webhook-endpoint)
defines the audience as the ACS resource identifier and links to the
[immutable resource ID instructions](https://learn.microsoft.com/azure/communication-services/quickstarts/voice-video-calling/get-resource-id).
It is not the public callback URL. Do not substitute the ARM `/subscriptions/...` resource path
merely because it is also called a resource ID.

Impact: supplying the public URL lets ACS receive a callback destination but rejects legitimate
callback tokens on audience validation. Supplying the ACS immutable identifier cannot satisfy the
current URL-typed setting or construct a usable callback destination. This is a configuration-contract
defect, not a missing tenant value.

Minimal correction: the foundation and integration owners must split the public HTTPS callback
base URL from the opaque ACS callback audience across settings, Bicep inputs/bindings, and gateway
construction. Keep JWT signature, issuer, expiry, and audience enforcement unchanged. Use the
existing ACS resource's `properties.immutableResourceId` or an explicitly verified external value
for the audience, and the app's public HTTPS URL for delivery. Update focused configuration,
gateway, and JWT tests with distinct values; keep the sole callback exclusion and public endpoints.

### C-02 Critical: Workspace Defaults Do Not Enforce Telemetry Retention

Requirement: Step 1B.3 and the research require 30-day content-free telemetry retention.

Evidence: [workspace retention](infra/modules/observability.bicep#L19) and
[component retention](infra/modules/observability.bicep#L35) are set to 30, but the module contains
no `Microsoft.OperationalInsights/workspaces/tables` resources. Microsoft documents
[90-day defaults for Application Insights tables](https://learn.microsoft.com/azure/azure-monitor/logs/data-retention-configure#log-tables-with-90-day-default-retention),
including AppDependencies, AppRequests, AppMetrics, and AppTraces. Component-level retention is
not a substitute for table retention in a workspace-based resource.

Impact: required application telemetry can remain for 90 days despite the apparent 30-day settings.
This is a missing retention control, independent of whether DR-03 policy approval has been obtained.

Minimal correction: the monitoring owner must explicitly configure analytics and total retention
to 30 days for the Application Insights tables used by this service, including dependencies,
requests, metrics, and traces, and any other enabled App* telemetry tables. Order table configuration
after table provisioning as required by the resource provider and verify effective settings.
Do not add a log archive or change public ingestion/query access. For a strict deletion-at-day-30
policy, also configure `immediatePurgeDataOn30Days` through the supported workspace API;
Microsoft notes that a 30-day workspace can otherwise retain data for 31 days. The policy owner
must approve the documented behavior of system tables such as Usage and AzureActivity separately.

### Major and Minor Findings

No additional confirmed Major or Minor product findings. Unsupported-role search results are
not treated as proof that a role is nonexistent. Existing-resource prerequisites, fresh compilation,
and runtime platform behavior are explicit external evidence gates below, not speculative defects.

## Checks and Evidence

Resumption on 2026-09-16 reread all five supplied artifacts in full and inspected all seven
Phase 1B modules. Existing plan, changes-log, planning-log, and unrelated worktree edits
were left untouched. No environment file was read.

Local tool discovery found neither `az` nor `bicep` on `PATH`; Node.js is available.
The changes log's historical Bicep CLI 0.47.16 success is preserved as a claim, not
treated as a fresh build. The cached role-search result contains zero results and
does not establish whether the configured role ID is valid.

PostgreSQL source satisfies the public-network decision and TLS requirements.
The identity module exports resource, principal, and client IDs only. Container App
source has public HTTPS ingress on port 8000, single revision mode, minimum and
maximum replicas of one, health probes, secret references, and the sole ACS callback
exclusion. External live evidence remains a validation limitation, not a product defect.

The standard standalone path `/home/codespace/.azure/bin/bicep` was also checked and was not
executable. Targeted searches of temporary and common installation locations found no compiler.
No compiler was installed. No fresh Bicep compilation or Azure validation was performed.
The historical claim of seven modules compiling with CLI 0.47.16 and zero warnings/errors remains
at [Phase 1 validation](.copilot-tracking/changes/2026-09-15/ask-my-human-tight-mvp-changes.md#L147).
The checked-in [generated template](infra/main.json#L586) contains the same role GUID and retention
settings; it proves neither current-source compilation nor Azure deployment validity.

Related-file search found [composition](infra/main.bicep),
[parameter bindings](infra/environments/dev.bicepparam), the generated template, and
[CI](.github/workflows/ci.yml#L74), which are later-phase surfaces not enumerated in the Phase 1B
change entries. Relevant wiring was checked; later-phase acceptance was not inferred from their
existence. Both cross-scope support modules are explicitly recorded in the changes log and DD-04.
No unlogged additional Phase 1B module or unauthorized networking resource was found.

Public documentation was consulted without authentication. Empty role-catalog searches and a
third-party role-page 404 are negative search evidence only. No tenant or role inventory was queried.
Report-only editor diagnostics passed after the progressive update; final document checks are
recorded at completion.

## Resolved Questions and External Gates

### E-01 ACS Role Definition and Operation Permissions

The [literal role GUID](infra/modules/communications-acs-role-assignment.bicep#L9) is
`0d8b7e87-0907-4e9d-a49d-ad2166c4bf2e`, named `azureCommunicationServicesDataOwnerRoleId` locally.
The local variable name is not an authoritative role definition. Public Microsoft role-catalog
and exact-GUID searches did not supply a definition. Therefore no claim of a nonexistent role,
successful authorization, or least privilege is made.

Disposition: external acceptance gate, not an indeterminate product finding. Before deployment,
the communications owner must obtain a sanitized definition for this exact GUID from the target
subscription: role name/type, actions, dataActions, exclusions, and assignable scopes. Compare it
with the implemented create-call, recognize, play, and hang-up operations. If absent or unsuitable,
replace only the GUID/reference with a verified least-privilege role, or expose a verified role-definition
input if a tenant-managed custom role is required. Do not invent action names or replace it with
subscription-wide Owner/Contributor. The general
[ACS authentication documentation](https://learn.microsoft.com/azure/communication-services/concepts/authentication)
supports Entra authentication for Call Automation but does not establish this GUID's permissions.

### E-02 Distinct Managed Identities

The Container App user-assigned identity is correctly bound for image pull and selected through
[AZURE_CLIENT_ID](infra/modules/container-app.bicep#L167) for
[DefaultAzureCredential](src/ask_my_human/main.py#L118). The Entra protected-resource client ID is
a separate auth registration, not the managed identity selector.

The [AI role assignment](infra/modules/communications.bicep#L49) correctly uses ACS's
system-assigned principal. This matches Microsoft's
[manual ACS-to-AI integration](https://learn.microsoft.com/azure/communication-services/concepts/call-automation/azure-communication-services-azure-cognitive-services-integration).
The existing ACS input explicitly requires that identity. No correction to the principal is warranted.
The external ACS owner must confirm that it exists and is enabled; deployment identity permissions,
cross-subscription tenant compatibility, role propagation, eligible source number, and AI-region
support remain DR-01/DR-04 checks. Do not mutate the externally owned numbered ACS resource implicitly.

### E-03 Registry, Auth and Runtime Evidence

AcrPull is scoped to the selected registry and assigned before app creation. The registry owner must
confirm its permission mode supports AcrPull, its managed-identity token settings, and image availability.
DR-02 must supply the Entra tenant, resource registration, AskHuman.Invoke application-role grants,
and authorized clients. Public endpoint decisions remain approved. An authorized later validation
must verify image pull, healthy probes, unauthenticated HTTP/MCP rejection, header trust, and genuine
callback acceptance after C-01. No extra auth exclusions are recommended from local inspection.

### E-04 Retention Approval and Local Build Evidence

DR-03 must approve effective telemetry retention, including platform exceptions and purge semantics,
and distinguish 24-hour live-row purge from the
[seven-day PostgreSQL backups](infra/modules/postgresql.bicep#L36). Backup retention is not evidence
that the live-row purge is broken and cannot be silently represented as 24-hour physical erasure.
DR-05 still requires target-client timeout/cancellation evidence. Neither is a Phase 1B code finding.

A fresh module build remains unavailable locally. On an authorized machine with an existing Bicep
compiler, compile all seven modules independently with `bicep build <module> --stdout` and compile
the composition root, capturing diagnostics without writing generated files into the worktree.
Parameter compilation must use synthetic values, never a secret environment file. CI defines this
check, but no CI run result was obtained during this review.

## Coverage and Next Validations

All four steps, all seven modules, and every listed Phase 1B success criterion were compared with
the changes log and verified source. No planned module is missing. PostgreSQL source criteria pass;
identity and communications resources are present with E-01 acceptance outstanding; observability
fails effective retention; Container App resources are present but fail callback compatibility.
The four checked plan entries overstate acceptance while C-01/C-02 remain. No plan or log was edited.

Recommended next validations, not completed in this session:

* [ ] Correct C-01 through the foundation/integration owners; test distinct callback URL and ACS immutable audience, including valid and wrong-audience signed tokens.
* [ ] Correct C-02 through the monitoring owner; inspect compiled table retention and, after authorization, effective analytics/total retention and purge behavior.
* [ ] Obtain E-01's exact ACS role definition and verify its permissions against all implemented SDK operations before deployment or paid calls.
* [ ] Run fresh independent builds for all seven modules and the root using an already available compiler and synthetic parameter values.
* [ ] Resolve DR-01 through DR-04 with resource owners, including ACS identity, ACR permission mode, Entra role grants, and retention/backup approval.
* [ ] After separate authorization, review what-if, deploy, verify probes and auth boundaries, then run the gated call/client matrix and DR-05 checks.

Final report checks: editor diagnostics and all 36 local links and line anchors passed.
Completion markers passed. The initial whitespace check found a missing final newline;
the report was corrected for a focused rerun.
Implementation files, plans, research, and approved endpoints are unchanged by this validation.

## Clarifying Questions

No unanswered product-design question is needed to act on C-01 or C-02.
External owners must provide the E-01 role definition, confirm the existing ACS system identity and
registry mode, and approve DR-03 retention semantics. These requests need sanitized evidence only;
do not provide tokens, phone numbers, passwords, connection strings, or environment-file contents.
