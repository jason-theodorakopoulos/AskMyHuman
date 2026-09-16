---
title: Phase 5 Azure Readiness Research
description: Sanitized read-only inventory and deployment gate evidence for AskMyHuman.
ms.date: 2026-09-16
---

## Status

Complete as a bounded research inventory on 2026-09-16. Phase 5.1 remains
blocked; this is not deployment approval. No what-if, deployment, provider
registration, Entra assignment, number purchase, or call was performed.
No product files, environment files, or planning logs were edited by this research.

## Questions

* Validate the supplied deployment identity and identify accessible subscriptions.
* Match the supplied ACS endpoint, count purchased numbers, and assess outbound suitability.
* Identify relevant existing registry and deployment resources and permission gaps.
* Establish whether a protected API and authorized client already satisfy DR-02.
* Resolve available evidence for DR-01 through DR-05 and recommend low-cost settings.

## Executive Findings

* Service-principal login succeeded. One enabled subscription is visible and is the isolated CLI session default; no visible subscription ambiguity exists.
* The only visible resource group is rg-askmyhuman in swedencentral. Its resource inventory returned zero resources. No accessible ACS or ACR appeared in subscription-level inventories.
* The supplied ACS key successfully enumerated exactly one purchased US toll-free number, enabled for both inbound and outbound calls. The destination parses as a valid Greek number. No literal numbers were retained.
* The ACS endpoint could not be matched to an ARM resource with this identity. Resource name, resource ID, resource group, ARM location, data location, and managed identity remain unknown. The successful data-plane inventory does not establish management-plane access.
* The deployment identity has conditional Owner permission only on rg-askmyhuman. Its condition does not exclude the three role definitions used by the current Bicep. Permission on the unidentified ACS resource or an external ACR is not established.
* The supplied Entra client ID identifies sp-askmyhuman, the deployment principal. Its service principal exposes no app roles. Reading its application registration and a targeted AskMyHuman application search were denied. A usable protected API and authorized agent cannot be inferred.
* Existing-number outbound capability does not prove international reachability to Greece. Public documentation reviewed did not establish that route for this resource. Keep destination support blocked pending resource-owner or Azure support evidence.
* Retention approval and the actual MCP client remain unknown. All five DR gates remain open, although parts of DR-01, DR-02, and DR-04 now have evidence.

## Safety And Method

Node.js util.parseEnv parsed the ignored .env file in memory. The file was never
shell-sourced or passed to read_file. The malformed ACS_ENDPOINT connection
string was split into structured key/value entries, and only its endpoint was
used in memory. ACS_KEY authenticated the read-only phone inventory.

Azure CLI 2.77.0 was downloaded from Microsoft's package repository and unpacked
under /tmp without elevated privileges. Its bundled interpreter ran the CLI;
repository package dependencies were not changed. The existing workspace Python
environment was selected during tooling preparation. Temporary npm tooling used
the official ACS PhoneNumbersClient and libphonenumber-js.

Login used ENTRA_TENANT_ID, ENTRA_CLIENT_ID, and CLIENT_SECRET from parsed values,
with output set to none. CLI subprocess stdout and stderr were captured;
only allowlisted metadata and sanitized error categories were printed.
Telemetry and CLI file logging were disabled through environment settings.
CLI authentication state is isolated under /tmp/askmyhuman-azure-inventory-config;
it is sensitive local authentication state, not a research artifact, and must not
be copied into the repository. No credential, token, connection string, or phone
number is included in this document.

One shared-terminal tool response contained another agent's test output. It was
excluded as inventory evidence; the intended Azure operation was rerun and
returned the explicit sanitized results recorded below. This research does not
assess the other agent's application validation.

## Nonsecret Deployment Identifiers

| Input | Verified value | Interpretation |
| --- | --- | --- |
| Tenant ID | 1646c59f-f970-4e3c-8852-0cb99f87d565 | Successful service-principal login tenant |
| Subscription ID | 5d5d25ff-7493-4644-9e84-ae90d5fded3a | Only visible enabled subscription; isolated CLI default |
| Subscription name | ME-MngEnvMCAP721432-dkalamaras-1 | Accessible subscription candidate |
| Deployment application ID | 15a31f53-3ec3-4c0b-89fa-c7392d70062b | Not a verified protected API ID |
| Deployment principal object ID | a68c8323-a3bc-4db0-9cab-2f1e90f7a2e8 | Matches the enabled sp-askmyhuman service principal |
| Deployment principal name | sp-askmyhuman | ServicePrincipal type Application |
| Resource group candidate | rg-askmyhuman | Sole visible group; currently empty |
| Resource group location | swedencentral | Group metadata, not a verified service-region compatibility decision |
| Resource group ID | /subscriptions/5d5d25ff-7493-4644-9e84-ae90d5fded3a/resourceGroups/rg-askmyhuman | Scope of conditional Owner assignment |

Recommend rg-askmyhuman as the deployment-group candidate because it is named for
this project and has verified scoped permissions. Do not export it as an
approved target automatically. Recommend evaluating swedencentral first, but
ACS/Speech compatibility, quotas, provider registration, and organizational
region approval remain unverified. No existing ACR candidate can be recommended.
Inventories are limited to this identity's visibility; absence is not proof of
tenant-wide nonexistence.

## Azure Evidence

| Read-only operation | Sanitized result |
| --- | --- |
| az login with service principal | Success |
| az account list | One enabled subscription, default true |
| az resource list for communicationServices | Empty visible result |
| az group list | One group, rg-askmyhuman, swedencentral |
| az resource list in rg-askmyhuman | Zero resources |
| az acr list | Empty visible result |
| ARM subscription permissions GET, API 2022-04-01 | Empty permission list |
| ARM rg-askmyhuman permissions GET, API 2022-04-01 | actions contains wildcard; no notActions or dataActions |
| az role assignment list for deployment object ID | Conditional Owner on rg-askmyhuman only |
| az ad sp show for supplied client ID | Enabled sp-askmyhuman; appRoles empty; appRoleAssignmentRequired false |
| az ad app show for supplied client ID | authorization-denied |
| Graph applications GET filtered to AskMyHuman display-name prefix | authorization-denied; stopped further application search |
| ACS PhoneNumbersClient.listPurchasedPhoneNumbers | Success; one owned US toll-free number; one outbound-capable number |
| In-memory destination parsing | Valid format; country GR |

No Graph app-role assignment enumeration was attempted after application access
was denied and no protected API or real agent was established. No role or API
consent was changed. Provider states and live SKU availability were not queried:
they do not resolve the missing ACS, ACR, identity, or approval gates.

### Conditional Owner Interpretation

The assignment condition is version 2.0. It excludes roleAssignments write and
delete when the requested or existing role definition ID is any of:

* 8e3af657-a8ff-443c-a75c-2fe8c4bcb635
* 18d7d88d-d35e-4fb5-a5c3-7773c20a72d9
* f58310d9-a9f6-439a-9e8d-f62e7b41a168

The template instead assigns these roles, none excluded by that condition:

* Azure Communication Services Data Owner: 0d8b7e87-0907-4e9d-a49d-ad2166c4bf2e
* Cognitive Services User: a97b65f3-24c7-4388-baec-2e87135dc908
* AcrPull: 7f951dda-4ed3-4680-a7ca-43fe172d538d

The observed assignment permits ordinary resource-group Bicep resource creation,
nested deployments, and those role assignments within rg-askmyhuman, subject to
Azure Policy, deny assignments, quotas, and provider prerequisites not assessed
here. It does not grant authority at subscription scope or on unidentified
external resource groups. communications.bicep and container-app.bicep create
nested role-assignment deployments in the existing ACS and ACR groups, so both
resource-level RBAC and deployment permission on those groups must be established.

ACR push/build permission is not verified against any registry because none is
visible. Group Owner would ordinarily cover classic RBAC ACR management/build and
push actions on a registry inside this group, but this must be checked against
the actual registry's permission mode and network policy. For an external ACR,
verify build/task scheduling rights separately from push rights. For an
ABAC-enabled registry, review repository roles and managed-identity pull support;
the current AcrPull assignment cannot be assumed sufficient.

### ACS Suitability

The blank source-number input can be populated mechanically from the sole owned
outbound-capable inventory entry in a future authorized secure configuration
step, without selecting among multiple numbers. Do not populate it yet: ARM
resource ownership, managed identity, and Greece routing suitability are not
established. No number was printed or stored, and no .env change was made.

US numbering geography is not ACS data location. The inaccessible ACS resource
may lie outside the identity's visible scope or subscription; its location must
not be guessed from the phone country or deployment-group location. Successful
ACS_KEY access does not grant the managed identity permissions required by the
application, and substituting that key for managed identity is not recommended.

Microsoft's US number-management page confirms make-call capability for US
toll-free numbers, but that table does not establish international reach to
Greece. The telephony overview documents target-country-dependent outbound
pricing, not this resource's permitted routes. The bounded documentation review
did not prove either support or a blanket prohibition for the observed route.
Obtain applicable outbound-country policy and resource-specific entitlement
evidence from its owner or Azure support before treating it as suitable.

## Decision Gates

| Gate | Resolved evidence | Unresolved blocker and next action |
| --- | --- | --- |
| DR-01 | ACS key valid; one owned outbound-capable US toll-free number; destination country GR | Supply existing ACS ARM ID and authorized management visibility; verify system-assigned identity, data location, compatible Speech region, and Greece outbound eligibility. Number purchase is neither necessary to infer nor authorized. |
| DR-02 | Tenant and deployment identity validated; supplied service principal has no app roles | Identify protected API app ID with enabled AskHuman.Invoke application role, actual agent app ID, and granted app-role assignment. Tenant administrator must supply sanitized evidence or authorized read access; do not equate deployment credentials with API credentials. |
| DR-03 | Bicep fixes request retention at 24 hours and telemetry at 30 days | Obtain organizational approval, approved alternatives, or a recorded release exception. Technical defaults are not consent. |
| DR-04 | One visible subscription; empty project group in swedencentral; scoped conditional Owner understood | Confirm target group and region; identify existing ACR ID/name/server and usable build/push mode; establish rights on ACS/ACR groups. If no registry exists, creation requires an explicit scope/plan decision, not an implicit inventory action. |
| DR-05 | Plan requires a 225-second timeout and Streamable HTTP cancellation | Identify actual MCP client/version, configure its timeout, and provide evidence or an approved predeployment exception. Runtime cancellation/live acceptance still belongs after verified deployment. |

The Phase 4 post-documentation gate is also a Phase 5 dependency. The plan was
unchecked at the research read; another agent owns local validation and release
work. This inventory does not attest that dependency is complete.

Current gates safely prevent any deployment only when the documented process is
followed. The helper does not enforce approvals: nonempty placeholders could pass
its environment checks. Its current inputs are missing, so it would fail the
presence check now, but that is not a durable release gate. Do not run what-if
until DR values or explicit permitted exceptions are reviewed and recorded.

## Exact Configuration Gaps

Missing or blank values observed, reported by key name only:

* AZURE_RESOURCE_GROUP
* AZURE_LOCATION
* CONTAINER_REGISTRY_NAME
* CONTAINER_REGISTRY_SERVER
* CONTAINER_REGISTRY_RESOURCE_ID
* POSTGRES_ADMIN_PASSWORD
* ACS_SOURCE_PHONE_NUMBER
* ENTRA_CLIENT_SECRET
* EXISTING_ACS_RESOURCE_ID
* ACS_CALLBACK_AUDIENCE

AUTHORIZED_AGENT_APP_IDS contains a placeholder. ENTRA_CLIENT_ID is populated,
but identifies the deployment principal, not a verified API. CLIENT_SECRET is
available for deployment login; it must not be blindly aliased to
ENTRA_CLIENT_SECRET, which configures the protected API's Container Apps
authentication. MCP_ALLOWED_HOSTS is present, but no deployed public hostname
exists to establish its correctness. MY_MOBILE_NUMBER is present and passed
in-memory format validation; authorization to call remains separately gated.

ACS_CALLBACK_AUDIENCE and MCP_ALLOWED_HOSTS need an approved public hostname.
The current template returns its platform FQDN only after deployment while
requiring both inputs before deployment. Resolve that bootstrap dependency using
an approved known custom hostname or a reviewed staged configuration flow, never
by guessing a platform FQDN or weakening validation. CONTAINER_IMAGE can be
derived from an approved registry and reviewed commit later; this inventory did
not build or publish an image.

## Minimal Recommended Changes

No changes below were implemented; coordinate them with the owning agents.

1. Add explicit fail-closed DR approval and placeholder validation before any
	Azure operation in scripts/deploy_azure.sh. Pin the approved subscription and
	validate the selected group, existing ACS, and registry scopes. Preserve
	read-only verify behavior without requiring deployment secrets.
2. Separate deployment-login credentials from protected-resource configuration.
	Add structured dotenv loading where needed, reject connection-string-shaped
	ACS_ENDPOINT for runtime use, and never shell-source the file.
3. Preserve a sanitized what-if change list for actual review. The helper
	currently discards stdout and proceeds from what-if directly to build/deploy;
	successful execution is not approval. Capture and sanitize stderr as well,
	rather than recommending unrestricted reruns that can expose secure inputs.
4. Build the reviewed commit's exact context, not an arbitrary dirty working tree
	tagged with HEAD. Verify a full immutable image reference; report healthState
	and readiness in addition to active/running state before any live-test gate.
5. Resolve the public-host bootstrap explicitly. Review Easy Auth health-path
	behavior: only callbacks are excluded today, while the helper expects an
	unauthenticated liveness response. Do not weaken API/callback authentication.
6. Parameterize Container App CPU/memory only if choosing the lower allocation;
	maintain minReplicas and maxReplicas at one. Retention changes, if approved,
	require updating main.bicep and the observability module's allowed value.

Cheap validation for the future implementation: bash -n on the helper; offline
mocked-az tests showing missing/unapproved/placeholder gates execute zero Azure
commands; captured-output redaction tests; Bicep compile to a temporary output;
and a local container startup/readiness and representative memory check at the
proposed smaller allocation. The owning agent should add mocked failure cases
for unhealthy revisions, unreviewed what-if, dirty build context, and hostname
bootstrap. Do not run what-if as an early validation substitute.

## Low-Cost Choices

| Component | Current configuration or recommendation | Qualification |
| --- | --- | --- |
| ACS | Reuse the existing numbered resource | No new purchase; recurring number rental and usage still apply; Greece route unverified |
| ACR | Prefer an eligible existing registry; Basic if separately approved creation becomes necessary | No existing registry visible. Basic is the lowest ordinary paid ACR tier, but actual registry eligibility, task/build permission, and feature needs remain unverified. |
| Container Apps | Keep consumption hosting and exactly one warm replica | Current allocation is 0.5 vCPU/1 GiB. Consider 0.25 vCPU/0.5 GiB only after memory/startup tests; scale-to-zero violates the current architecture. |
| PostgreSQL | Keep Standard_B1ms Burstable, 32 GiB, seven-day backup, no HA, no geo-redundant backup | Already a small baseline; region/SKU availability not attested. Do not trade away durable PostgreSQL semantics for unrelated cost work. |
| Azure AI services | Keep AIServices S0, usage-based | Existing communications module expects this kind. Do not substitute Speech F0 without a separate compatibility and quota review. |
| Observability | Keep PerGB2018 and approved retention; content-free low-volume telemetry | No ingestion commitment tier. A budget alert or daily cap is a separate approved action and can affect diagnostics. |
| Networking | Keep the approved public-endpoint architecture | No VNet, private endpoint, NAT, or dedicated environment added. Existing broad PostgreSQL Azure-services firewall remains a reviewed security trade-off. |

No live price quote, budget estimate, provider-registration proof, SKU capacity,
or free-tier entitlement is claimed. Resource-group metadata alone does not
prove a service SKU is deployable in that region.

## Necessary Clarifications

* What is the existing ACS ARM resource ID, and can its owner provide read access
  or sanitized resource/managed-identity metadata and Greece routing evidence?
* Confirm rg-askmyhuman as the target candidate and provide the existing ACR
  identity. If none exists, is a separately approved Basic registry creation
  acceptable, and which region is approved after ACS/Speech compatibility checks?
* Which protected API and real agent registrations should be used, with evidence
  of AskHuman.Invoke and its assignment? Do not send secret values in chat.
* Is 24-hour request retention and 30-day content-free telemetry approved?
* Which MCP client/version must demonstrate timeout and cancellation, and what
  approved public hostname will supply callback audience and allowed hosts?

## Deferred Verification Checklist

* [ ] Match ACS management resource, identity, data location, and Greece route.
* [ ] Verify selected ACR, permission mode, task/build and push rights, and external-group deployment rights.
* [ ] Verify protected API role and actual agent assignment with authorized Graph evidence.
* [ ] Obtain retention, region, hostname, and MCP-client decisions or explicit permitted exceptions.
* [ ] Check only the chosen region's relevant provider states, quotas, and SKUs after input selection.
* [ ] After all gates and Phase 4 evidence pass, authorize and review sanitized what-if separately.

## References

* .copilot-tracking/details/2026-09-15/ask-my-human-tight-mvp-details.md, lines 981-1085
* .copilot-tracking/plans/2026-09-15/ask-my-human-tight-mvp-plan.instructions.md, Phase 5 and dependencies
* .copilot-tracking/plans/logs/2026-09-15/ask-my-human-tight-mvp-log.md, DR-01 through DR-05 and DD-04/DD-05
* scripts/deploy_azure.sh
* infra/main.bicep
* infra/environments/dev.bicepparam
* infra/modules/communications.bicep
* infra/modules/communications-acs-role-assignment.bicep
* infra/modules/container-app.bicep
* infra/modules/container-app-acr-role-assignment.bicep
* infra/modules/postgresql.bicep
* infra/modules/observability.bicep
* [US number management](https://learn.microsoft.com/en-us/azure/communication-services/concepts/numbers/phone-number-management-for-united-states)
* [Number eligibility and capability](https://learn.microsoft.com/en-us/azure/communication-services/concepts/numbers/sub-eligibility-number-capability)
* [Telephony overview](https://learn.microsoft.com/en-us/azure/communication-services/concepts/telephony/telephony-concept)
* [PSTN calling quickstart](https://learn.microsoft.com/en-us/azure/communication-services/quickstarts/telephony/pstn-call)