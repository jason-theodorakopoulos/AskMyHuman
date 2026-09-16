<!-- markdownlint-disable-file -->
# AskMyHuman MVP Phase Summary

| Phase | Brief Description | Can Run in Parallel? | Status |
|---|---|---|---|
| **0. Foundation and Contract Freeze** | Establish Python tooling, schemas, domain models, interfaces, test fakes, configuration, and Bicep module contracts. | **No.** Must finish before development branches split. | Complete |
| **1A. Application Workstreams** | Build persistence, orchestration, telephony, security, HTTP APIs, platform APIs, MCP, and observability. | **Yes.** Eight independent workstreams. | Complete |
| **1B. Infrastructure Workstreams** | Build networking and PostgreSQL, identity and communications, monitoring, and Container Apps modules. | **Yes.** Four independent workstreams that also run alongside Phase 1A. | Complete |
| **2. Integration** | Compose the ASGI application and Bicep deployment. | **Yes.** Application and infrastructure integration run concurrently. | Complete |
| **3. Image, Local Environment, and CI** | Build the container image, Docker Compose setup, CI pipeline, and gated live-test harness. | **No.** Begins after both integration tracks finish. | Complete |
| **4. Local Validation and Documentation** | Run the complete local gate, update README, and validate the documented repository state. | **No.** Sequential release preparation. | Complete |
| **5. Azure Deployment and Live Validation** | Run Bicep what-if, publish an immutable image, deploy it, verify health, and execute live-call scenarios. | **No.** Deployment steps are ordered. | Automation complete; execution blocked on tenant-owned inputs. |
| **6. Final Validation and Handoff** | Rerun all repository checks, review release evidence, fix minor failures, or report blockers. | **No.** Final release gate. | Pending Phase 5 execution. |
