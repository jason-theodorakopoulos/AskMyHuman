<!-- markdownlint-disable-file -->
# Planning Log: AskMyHuman Tight MVP

## Discrepancy Log

Gaps and differences identified between the research, original README, and
implementation plan.

### Unaddressed Research Items

* DR-01: Selection of an existing numbered ACS resource remains a tenant-specific deployment input.
  * Source: .copilot-tracking/research/2026-09-15/tight-mvp-scope-research.md (Line 335) and .copilot-tracking/research/subagents/2026-09-15/parallel-implementation-layout-research.md (Lines 788-790)
  * Reason: The destination country, Azure billing address, subscription eligibility, regulatory documents, and eligible source number cannot be derived from the repository.
  * Plan treatment: Steps 0.4 and 1B.2 accept an existing ACS resource that already owns an outbound-enabled number. Step 5.1 blocks what-if and deployment until that resource and a compatible region are selected; the plan does not attempt number acquisition or ACS resource creation.
  * Impact: high for deployment readiness; no remaining implementation-sequencing gap
* DR-02: Microsoft Entra tenant and authorized agent identities are not supplied.
  * Source: .copilot-tracking/research/2026-09-15/tight-mvp-scope-research.md (Line 337)
  * Reason: Application registrations, role assignments, and client IDs belong to the target tenant.
  * Plan treatment: Implement configurable validation and gate deployment configuration on supplied identities.
  * Impact: high
* DR-03: The proposed 24-hour database retention and 30-day content-free telemetry retention need organizational approval.
  * Source: .copilot-tracking/research/2026-09-15/tight-mvp-scope-research.md (Line 338)
  * Reason: Product research selected technical defaults, but the organization owns data policy.
  * Plan treatment: Implement the defaults and require approval or an explicit configuration change before deployment.
  * Impact: medium
* DR-04: The target Azure region, existing Container Registry, and deployment identities are not selected.
  * Source: .copilot-tracking/research/subagents/2026-09-15/parallel-implementation-layout-research.md (Lines 785-811)
  * Reason: These values depend on subscription governance and cannot be derived from the repository.
  * Plan treatment: Keep them as secure deployment inputs and gate Azure what-if and deployment.
  * Impact: high
* DR-05: The target MCP client has not demonstrated a 225-second timeout and Streamable HTTP cancellation.
  * Source: .copilot-tracking/research/2026-09-15/tight-mvp-scope-research.md (Line 336)
  * Reason: Timeout ownership is client-specific.
  * Plan treatment: Verify against the deployed service before release acceptance.
  * Impact: high

### Plan Deviations From Research

* DD-01: The original README names Microsoft Foundry Voice Live API, while the implementation plan uses ACS Play and Recognize with Azure Speech.
  * Research recommends: Use Play and Recognize for a bounded spoken prompt-response MVP and reserve Voice Live for multi-turn clarification.
  * Plan implements: One choices or speech recognition action with no application media streaming.
  * Rationale: This satisfies approval and one free-form answer without two WebSocket protocols, PCM handling, buffering, interruption, or relay operations.
  * Source: .copilot-tracking/research/2026-09-15/tight-mvp-scope-research.md (Lines 223-252)
* DD-02: The plan fixes maximum replicas to one, narrowing the primary research's durability posture to the detailed MVP layout.
  * Research recommends: The primary research requires at least one warm replica and durable PostgreSQL coordination through process replacement; the parallel-layout research further recommends a one-replica maximum for this MVP.
  * Plan implements: Exactly one minimum and maximum replica while preserving database-backed restart safety.
  * Rationale: This follows the detailed implementation research and bounds session and concurrency behavior for the one-pending-request MVP. Horizontal scaling remains follow-on work rather than an unapproved architecture change.
  * Source: .copilot-tracking/research/2026-09-15/tight-mvp-scope-research.md (Lines 53-66) and .copilot-tracking/research/subagents/2026-09-15/parallel-implementation-layout-research.md (Lines 28-53, 421-424)
* DD-03: Durable technical-error replay extends the frozen internal request and repository contracts.
  * Plan specifies: Technical failures produce stable execution errors and accepted state survives process replacement.
  * Implementation differs: `HumanRequest` includes an internal failed state and sanitized error fields, and `RequestRepository` includes conditional error completion.
  * Rationale: Process-local error storage replayed `deadline_exceeded` after service replacement. Persisting the stable public error code and sanitized message satisfies restart durability without changing wire schemas.
* DD-04: Cross-scope Azure role assignments use two workstream-owned support modules.
  * Plan specifies: Communications and Container App module owners implement minimum role assignments in their assigned modules.
  * Implementation differs: Each owner added one nested role-assignment module scoped to the existing ACS or ACR resource group.
  * Rationale: Bicep rejects direct role assignments to resources outside the parent resource-group scope. Nested deployments preserve least privilege and the frozen public module interfaces.
* DD-05: Azure resources use public service endpoints instead of private VNet integration.
  * Plan specifies: The original design provisions a VNet, delegated subnets, private PostgreSQL DNS, and VNet-integrated Container Apps.
  * Implementation differs: The network module is removed, PostgreSQL enables public network access with TLS and an Azure-services firewall rule, and Container Apps uses its default public environment network.
  * Rationale: The user selected public connectivity on 2026-09-15 to reduce MVP infrastructure and deployment complexity. Application authentication, callback JWT validation, managed identity, TLS, and secret handling remain enforced.

## Implementation Paths Considered

### Selected: Contract-First Single Service With Parallel Adapters

* Approach: Freeze schemas, domain types, ports, settings, and infrastructure module contracts, then implement persistence, orchestration, telephony, security, HTTP, MCP, observability, and Bicep modules in parallel before two single-owner integration streams.
* Rationale: Workstreams own disjoint files and test against frozen boundaries. One Container App and one PostgreSQL database preserve the tight runtime shape.
* Evidence: .copilot-tracking/research/subagents/2026-09-15/parallel-implementation-layout-research.md (Lines 247-286, 447-573)

### IP-01: Voice Live Media Relay In The First Release

* Approach: Stream bidirectional ACS PCM audio through an application WebSocket into a separate Voice Live WebSocket for an LLM-led conversation.
* Trade-offs: Supports clarification, interruption, semantic turn detection, and function calls, but adds media framing, backpressure, session lifecycle, latency, and partial-failure handling.
* Rejection rationale: Approval and one free-form answer do not require multi-turn conversation. The added implementation and operational surface conflicts with the ship-fast requirement.
* Evidence: .copilot-tracking/research/2026-09-15/tight-mvp-scope-research.md (Lines 242-252)

### IP-02: MCP-First Domain And Orchestration

* Approach: Make MCP tool lifecycle and JSON-RPC envelopes the primary application abstraction.
* Trade-offs: Reduces the visible HTTP contract but couples state, callback processing, and tests to one agent protocol.
* Rejection rationale: ACS callbacks and PostgreSQL state exist independently of the waiting MCP request. A thin adapter preserves MCP support without protocol coupling.
* Evidence: .copilot-tracking/research/2026-09-15/tight-mvp-scope-research.md (Lines 254-256)

### IP-03: In-Memory Coordination

* Approach: Keep pending calls and waiting futures in the Container App process and omit PostgreSQL from the first demonstration.
* Trade-offs: Fewer initial resources and migrations, but accepted calls are lost on restart and independently delivered callbacks cannot rely on affinity.
* Rejection rationale: A paid call can outlive the initiating process. PostgreSQL is already in the proposed stack and supplies idempotency and terminal arbitration.
* Evidence: .copilot-tracking/research/2026-09-15/tight-mvp-scope-research.md (Lines 181-207, 258-260)

### IP-04: Azure Table Storage Coordination

* Approach: Store each request as a table entity and use ETags for conditional updates.
* Trade-offs: Durable and lightweight, but adds partition-key and optimistic-concurrency design while departing from the named PostgreSQL stack.
* Rejection rationale: It offers no demonstrated schedule advantage for this one-table workflow, and PostgreSQL maps directly to the required uniqueness and conditional SQL.
* Evidence: .copilot-tracking/research/subagents/2026-09-15/service-contract-decision-research.md (Lines 101-160)

### IP-05: Shared-File Feature Development

* Approach: Let every feature owner modify `main.py`, `pyproject.toml`, root fixtures, Bicep composition, and CI as needed.
* Trade-offs: Each branch can appear self-contained, but contract drift, lockfile conflicts, composition regressions, and merge ordering become frequent.
* Rejection rationale: Foundation and integration owners provide the same functionality with predictable merge boundaries and focused review.
* Evidence: .copilot-tracking/research/subagents/2026-09-15/parallel-implementation-layout-research.md (Lines 447-518)

## Parallelization Decisions

* PD-01: Phase 0 is sequential because every later workstream depends on frozen package, contract, configuration, port, fake, and Bicep module interfaces.
* PD-02: Application Phase 1A and infrastructure Phase 1B run concurrently after Phase 0.
* PD-03: All eight Phase 1A application workstreams have disjoint product and test ownership.
* PD-04: Four Phase 1B infrastructure workstreams own disjoint Bicep modules and never edit the composition root.
* PD-05: Application and infrastructure integration run concurrently because `src/ask_my_human/main.py` and `infra/main.bicep` do not overlap.
* PD-06: Image, Compose, CI, final documentation, deployment, and live tests remain sequential because they consume stabilized integration outputs.
* PD-07: `pyproject.toml`, `uv.lock`, `config.py`, contracts, ports, `main.py`, root fixtures, `infra/main.bicep`, CI, and README each retain a single named owner.

## Merge Controls

* MC-01: Dependency requests go to the foundation owner; only that owner changes `pyproject.toml` and regenerates `uv.lock` with the pinned uv version.
* MC-02: Changes to frozen schemas, settings, domain models, or ports require acknowledgment from every affected implementation owner before merge.
* MC-03: Feature owners export routers, factories, clients, repositories, and implementations. They do not edit `main.py`.
* MC-04: Bicep module owners implement frozen inputs and outputs. They do not edit `infra/main.bicep` or the environment parameter file.
* MC-05: Root `tests/conftest.py` contains only markers and safety guards; workstream fixtures remain local.
* MC-06: The application integrator merges only workstreams that pass their scoped validation commands.
* MC-07: The infrastructure integrator merges only modules that build independently.
* MC-08: Contract changes discovered during integration return to Phase 0 instead of being patched locally in composition files.

## Suggested Follow-On Work

* WI-01: Add a Voice Live media relay for natural multi-turn clarification (medium priority, large effort).
  * Source: DD-01 and IP-01
  * Dependency: Tight MVP live-call metrics and a confirmed need for clarification
* WI-02: Add asynchronous agent resume and durable result retrieval (low priority, medium effort).
  * Source: README.md explicitly excludes resume from MVP.
  * Dependency: Stable synchronous contract and demonstrated requests that exceed transport limits
* WI-03: Add multiple humans, roles, routing, and escalation (low priority, large effort).
  * Source: README.md future scope
  * Dependency: A contact and authorization model planned as a separate task
* WI-04: Add retry and fallback-channel policy (low priority, medium effort).
  * Source: README.md future scope
  * Dependency: Outcome telemetry showing acceptable reasons and budgets for retries
* WI-05: Evaluate horizontal scaling and distributed MCP session handling (low priority, medium effort).
  * Source: DD-02
  * Dependency: Load evidence exceeding one-request-at-a-time MVP capacity

## Validation Status

Validated on 2026-09-15. Pass.

Final validation found zero critical and zero major planning discrepancies. All
31 plan-to-details ranges point to the complete matching step. DR-12 is resolved
by the immutable image build, deployment, revision and probe checks,
authentication smoke checks, failure handling, and separately gated live-test
step. DR-01 through DR-05 remain tenant-owned external release inputs with
explicit resolution gates in Step 5.1, not unplanned implementation gaps. DD-01
and DD-02 remain intentional, research-backed decisions.

## Phase 5 Execution Status

Recorded on 2026-09-16.

Phase 5 implementation is complete and Phase 5 execution is blocked.

* Blocked: Steps 5.1, 5.2, and 5.3 need an Azure subscription, a container
  registry, an ACS resource with an outbound-enabled number, and the Entra
  registrations described by DR-01 through DR-05. None are available in the
  implementation environment, and Step 5.3 places billable calls.
* Ready to run: `scripts/deploy_azure.sh what-if`, then
  `scripts/deploy_azure.sh deploy`, then
  `RUN_LIVE_AZURE_TESTS=1 uv run pytest -m live tests/e2e/test_live_call.py -vv`.
* DR-01 through DR-05 remain unresolved and stay tenant-owned release inputs.

## Additional Follow-On Work

* WI-06: Fix the pre-existing strict-typing errors in the test suite (medium
  priority, small effort).
  * Source: `uv run mypy src tests` reports 36 errors across 8 test modules that
    predate Phase 2 composition. `src` alone is clean, so the CI typing job is
    red independently of the composition and deployment work.
  * Dependency: None.
* WI-07: Confirm during the first real deployment that Container Apps health
  probes reach the container without passing through the authentication
  sidecar, since `unauthenticatedClientAction` is `Return401` and only the ACS
  callback path is excluded (low priority, small effort).
  * Source: `infra/modules/container-app.bicep`
  * Dependency: Step 5.2

