<!-- markdownlint-disable-file -->
# Review Log: AskMyHuman Implemented Phases

## Metadata

* Date: 2026-09-16
* Plan: `.copilot-tracking/plans/2026-09-15/ask-my-human-tight-mvp-plan.instructions.md`
* Changes: `.copilot-tracking/changes/2026-09-15/ask-my-human-tight-mvp-changes.md`
* Research: `.copilot-tracking/research/2026-09-15/tight-mvp-scope-research.md`
* Prior review: `.copilot-tracking/reviews/2026-09-15/ask-my-human-tight-mvp-plan-review.md`
* Scope: All implemented work, including integration and release files omitted from the current changes log. No Azure deployment or paid live calls are authorized by this review.
* Existing changes: Plan, planning log, and changes log were modified before review; preserve them.

## Status

Overall: Blocked for release acceptance; local implementation corrections are
complete, with the post-documentation gate pending final recording below.
Remaining confirmed local findings: 0 critical, 0 major, 0 minor.
Follow-up groups: 4, all external or explicitly deferred release work.

Reviewed state: the working tree based on `a6756d741f736560f79e510cbcb0fbd0e90d3b18`.
Existing user changes were preserved. No commit, branch, publication, Azure
deployment, or paid call was performed by this review continuation. The private
environment file was not read or changed; only its public example was updated.

The dated RPI files are preserved pre-fix evidence. Their Failed/Partial labels
do not describe the final corrected code; this log is the consolidated resolution
record. Release evidence is not inferred from local tests or checked plan boxes.

## Initial Hypothesis And Check

The changes log's claim that Phase 2 is intentionally unimplemented conflicts with the implemented composition root in `src/ask_my_human/main.py` and `tests/integration/test_asgi_app.py`. Run the ASGI tests to distinguish working integration from scaffolding, then reconcile the implementation inventory without claiming unexecuted deployment gates.

## Phase Validation

| Phase | Local Assessment | Evidence And Remaining Gates |
| --- | --- | --- |
| 0 | Verified | Prior product review retained; current schema, settings, contract, fake and dependency gates pass. Publication is separate. |
| 1A | Corrected and verified | [Application report](../rpi/2026-09-16/ask-my-human-tight-mvp-plan-001-validation.md); lifecycle, PostgreSQL, callback, authorization, maintenance and telemetry regressions pass. |
| 1B | Corrected and compiled | [Infrastructure report](../rpi/2026-09-16/ask-my-human-tight-mvp-plan-002-validation.md); all seven modules compile; audience and effective table retention repaired. Exact ACS role and tenant prerequisites still require external evidence. |
| 2 | Corrected and verified | [Composition report](../rpi/2026-09-16/ask-my-human-tight-mvp-plan-003-validation.md); mounted MCP, callback forwarding, lifespan and readiness tests pass; root and parameters compile. |
| 3 | Corrected and verified locally | [Release report](../rpi/2026-09-16/ask-my-human-tight-mvp-plan-004-validation.md); image build/runtime, migrations, MCP listing, private logs, CI commands and stubbed deployment tests pass. Live harness is implemented, not live-accepted. |
| 4 | Corrected; final rerun recorded below | [Documentation report](../rpi/2026-09-16/ask-my-human-tight-mvp-plan-005-validation.md); inventory and public behavior corrected. User approved DD-06 to remove the command-order conflict without waiving release gates. |
| 5 and 6 | Release blocked | Deployment and live-test tooling reviewed and locally tested. What-if approval, publication, actual healthy revision and live acceptance are not executed evidence. |

## Quality Validation

* [Owned implementation quality](../quality/2026-09-16/ask-my-human-tight-mvp-quality.md) records security, composition, observability and configuration corrections.
* [Cross-phase quality audit](../quality/2026-09-16/ask-my-human-tight-mvp-cross-phase-quality.md) identified one additional critical cleanup defect and four major race/producer-consumer defects. All five were corrected and covered by focused regressions.
* Named Implementation Validator invocations were attempted but lacked repository tools in their restricted sessions. They produced no usable independent validation and are not counted as successful runs. An implementation-capable independent audit, parent source inspection and executable gates supplied the actual quality evidence.
* Final findings counts are deduplicated across phase reports. No unresolved local finding is hidden by summing overlapping reports or by treating external prerequisites as passing tests.

## Findings And Corrections

| Area | Corrections | Regression Evidence |
| --- | --- | --- |
| Deadline and cancellation | Bound admission, creation, recognition, polling and cleanup; preserve creator versus joined-waiter ownership and durable terminal results. | [Service tests](../../../tests/unit/application/test_service.py) include stalled dependencies and task cancellation. |
| Callback lifecycle | Preserve connected, technical and playback events, verify call IDs and request kind, start recognition only after a durable once-only claim. | [Callback parser tests](../../../tests/unit/telephony/test_events.py), service and PostgreSQL tests. |
| Terminal races | SQL rejects success after expiry/work cutoff; late connections after cancelled/expired creation trigger cleanup; losing expiry does not interrupt winning acknowledgement. | Late-connection and losing-expiry tests first failed, then all 43 service tests passed. |
| Persistence | Add [recognition-guard migration](../../../migrations/versions/20260916_0002_recognition_guard.py), preserve stable error replay, return stale calls for bounded cleanup. | [Repository tests](../../../tests/integration/persistence/test_repository.py) and actual image migration to head. |
| Maintenance and lifespan | Retry on transient errors, reconcile pending metrics, clean up stale calls, drain tasks and close resources on cancelled startup; failed loops invalidate readiness. | Maintenance unit and ASGI integration tests. |
| Authentication | Share trusted principal, role and allowlist authorization across HTTP/MCP; remove SDK-token fallback; separate HTTPS callback URL from ACS immutable audience. | Mounted authorized/missing/roleless/disallowed principal matrix and distinct audience tests. |
| Discovery | Cap streamed document bytes and total elapsed time; bound unknown-key refresh churn. | Oversized/slow stream and refresh cooldown regressions. |
| Telemetry | Remove raw exception/access logs, attach content-free HTTP spans, instrument awaited operations, errors and pending state. | Composed exporters and actual image query/password sentinel checks. |
| Infrastructure | Enforce 30-day analytics/total retention on App tables, preserve approved public endpoints and sole callback auth exclusion, bind independent callback settings. | Bicep 0.47.16 builds all modules/root/parameters. Effective tenant retention remains an external gate. |
| Image and local environment | Pin verified Python image digest, one Uvicorn worker, no access logs; loopback Compose ports and exact host ports. | Docker build, Compose parsing, runtime health/MCP smoke. |
| Deployment | Default help; reviewed clean-source snapshot; digest provenance; approval bound to target/parameters/what-if; exact healthy/current revision, traffic and bounded authenticated probes; explicit rollback. | [Offline deployment tests](../../../tests/unit/test_deploy_script.py), Bash and ShellCheck. |
| Live harness | Fail-closed opt-in/preflight, mandatory evidence/query tooling, exact outcome/timing/MCP/cancellation/race checks, independent call-count attestations, privacy ingestion and retention cleanup. | [Harness regressions](../../../tests/unit/test_live_harness.py): 145 offline tests; 20 live scenarios skip without consent. |
| Handoff contracts | Preflight requires actual HTTP 400 invalid_request; normalize optional null answers without weakening validation; consume verifier JSON with provenance and separate database approval. | Actual in-process HTTP responses and offline deployment verifier outputs pass harness regression tests. |
| Documentation | Correct deadline/replay semantics, deployment claims, examples, phase inventory and Markdown. DD-06 records user-approved local-only Phase 4 command evidence. | Document diagnostics and post-edit whitespace gate; no external command success fabricated. |

### Implementation Notes

* Apply the additive Alembic migration before using the updated repository; image startup applies it automatically.
* Configure the new `ACS_CALLBACK_URL` with the complete HTTPS callback endpoint and `ACS_CALLBACK_AUDIENCE` with the verified immutable ACS ID, not the URL or ARM resource path.
* The development example preserves the user's added fields. Credential-bearing local settings were not copied into tests, logs or tracking documents.
* The image smoke uses an isolated internal database network namespace and synthetic settings, creates zero request rows and places no calls.
* The approved one-app/one-replica/PostgreSQL/public-endpoint architecture and public JSON schemas remain unchanged. No queue, worker, fallback channel or Voice Live relay was introduced.

## Validation Commands

| Check | Result | Output |
| --- | --- | --- |
| `uv lock --check` | Pass | 123 packages resolved; lock current |
| `uv sync --frozen --all-groups` | Pass | Locked environment synchronized; harmless cross-filesystem hardlink fallback |
| `python scripts/export_schemas.py --check` | Pass | No schema drift |
| `ruff format --check .` | Pass | 89 files already formatted |
| `ruff check .` | Pass | All checks passed |
| `mypy src tests` | Pass | No issues in 56 source files |
| Non-live pytest with branch coverage and 90% floor | Pass | 429 passed, 20 deselected; 91.28% coverage |
| Live selection with `RUN_LIVE_AZURE_TESTS=0` | Pass | 20 skipped; no credentials required |
| Docker build and application-container pytest | Pass | Encoded-password migration, health and private logging verified |
| `scripts/smoke_image.sh ask-my-human:mvp` | Pass | Migration head, health, authorization rejection, MCP initialization/tools-list, zero call rows and private logs |
| `docker compose --env-file /dev/null config --quiet` | Pass | No private environment file loaded |
| Bash syntax and ShellCheck 0.11.0 | Pass | Both deployment and smoke scripts clean |
| Bicep 0.47.16 build | Pass | Seven modules, root and dev parameters; synthetic CI values only |
| Public environment example validation | Pass | Separate callback endpoint and audience accepted |
| Source/test/document diagnostics | Pass for checked files | No relevant editor errors |
| Post-documentation complete gate and `git diff --check` | Pending final recording | Required after the DD-06 and README update |

Earlier failed checks were repaired, not omitted: the old migration-head assertion,
one-second successful-verification test timeout, isolated smoke network routing,
MCP Python schema accessor, and final helper formatting/type inference all have
passing subsequent focused checks. The sole pytest warning is Starlette's
deprecated AnyIO BlockingPortal alias; no unrelated dependency churn was added.

## Follow-Up Work

### Deferred From Scope

1. Tenant/communications owners: resolve DR-01 through DR-04, including the exact configured ACS role GUID's permissions, immutable audience, ACS identity/eligible number, registry permission mode, Entra grants and approved retention/backup policy. No role replacement was invented from inconclusive public search results.
2. Release operator: authorize publication/mutation, review what-if, publish the reviewed clean snapshot and verify the actual immutable healthy revision and authentication boundary. Stubbed checks do not establish Azure behavior.
3. Product/test operator: separately authorize and execute the real HTTP/MCP outcome, race, cancellation, call-count, privacy/ingestion and retention matrix; supply target-client DR-05 and approved carrier limitations.
4. Repository owner: request commit/publication and clean-checkout reproduction when ready. The current changes remain uncommitted because no commit was requested.

### Discovered During Review

No remaining local corrective item. The five cross-phase findings and the
documentation phase-order conflict are resolved. Follow-up release evidence
above remains required; local completion is not release approval.