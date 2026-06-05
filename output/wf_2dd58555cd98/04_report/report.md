# Report

_Agent: `assistant` (General Assistant)_  
_Status: `success` · attempts: 1_

---

# `/monthly` Feature — Engineering Analysis Report

## Overview

The `/monthly` feature is a **route fragment and aggregation mode** within the Skalbox platform, not a standalone module. It surfaces primarily through two endpoint match points in `TrailController` (`src/main/java/io/spdigital/skalbox/ubm/controller/TrailController.java`, lines 103 & 126), anchored to the canonical constant `ChartConstants.CSV_MONTHLY` (imported at line 30 of the same file). The feature exposes monthly aggregation and CSV-export capabilities under the `/ubm/trail` namespace, with the underlying data-shaping work delegated to the `chart` bounded context.

**Inventory snapshot:**
- 20 Java files (~695 KB), 100% Java
- 9 of 20 files are tests — meaningful existing coverage, not greenfield
- Spans 7 packages across `ubm`, `chart`, `auth`, and `accounts` bounded contexts
- M2M-secured (`read:spd.skalbox.trails` scope) — not user-JWT facing

## Architecture

**Layered, reactive Spring WebFlux** applied per bounded context:

```
HTTP (M2M-secured) ──► Controller layer
                              │
                              ▼
                       Service interface ──► ServiceImpl
                              │
                              ▼
                        DTOs + domain exceptions
```

**Key components by package:**

| Layer | File | Role |
|---|---|---|
| Web (entry) | `ubm/controller/TrailController.java` | Primary `/monthly` HTTP entry under `/ubm/trail`; M2M-scoped |
| Web (chart) | `chart/web/controller/ChartController.java`, `PrivateChartController.java` | Public/internal split for chart endpoints |
| Service | `chart/service/ChartService.java` + `ChartServiceImpl.java` | Core aggregation/charting logic — likely owner of monthly rollup |
| DTOs | `chart/model/dto/MDHChart.java`, `BillExplainer.java` | Response shapes for monthly views |
| Errors | `chart/exception/ChartApiException.java` | Module-local exception type |
| Auth | `auth/service/Auth0ServiceImpl.java` | Identity/token resolution |
| Accounts | `accounts/service/AccountServiceImpl.java` | Account lookup for monthly views |

**Cross-cutting conventions:**
- Reactive types (`Mono<T>` / `Flux<T>`) throughout
- Lombok-driven constructor injection (`@RequiredArgsConstructor`, `@Slf4j`)
- Custom annotations: `@Loggable` (request/response logging) and `@SkalboxM2MSecured` (OAuth scope enforcement)
- `LocalDate` + `@DateTimeFormat(iso = ISO.DATE)` for query-param date handling
- `ChartConstants.CSV_MONTHLY` is the canonical token branching monthly vs. other granularities — a single chokepoint for the mode flag

**Bounded-context observation:** `TrailController` composes services from `chart`, `smrd`, `account`, and `trail`; monthly logic flows `TrailController → ChartService(Impl) → DTOs`. The `chart` package owns aggregation; `ubm` owns routing and orchestration.

## Quality & Risk

**Strengths**
- **Test footprint is real:** 9/20 files are tests, spanning adjacent domains (`smrd`, `profilextractor`, `payment`, `refund`, `security`). `/monthly` is integration-tested against neighboring services, not isolated.
- **Clear interface/impl separation** across all services (`ChartService` / `ChartServiceImpl`, mirrored for Account, SMRD, Payment, Refund, User, ProfileXtractor) — supports mocking and refactoring safely.
- **Single source of truth for the mode flag:** `ChartConstants.CSV_MONTHLY` centralizes the monthly branch; reduces the risk of stringly-typed drift.
- **Security posture is explicit:** every entry point is M2M-scoped, removing ambiguity about caller identity.

**Risks & Gaps**
- **`/monthly` is not a first-class concept** — it is a route fragment plus a constant. Changes ripple across the `TrailService ↔ ChartService` boundary, and there is no single "monthly" abstraction to test or evolve in isolation.
- **Public vs. internal controller split (`ChartController` vs. `PrivateChartController`) is undocumented in the inventory.** Adding a new monthly endpoint without confirming the intended exposure boundary risks leaking internal data shapes (`BillExplainer`, `MDHChart`) externally.
- **Build/config files (`pom.xml`, `application.yml`, security config) were filtered out** of the scan. Wiring, dependency versions, and scope-to-route mapping cannot be verified from the inventory alone.
- **Architecture analysis was truncated** (the architect agent reported a permissions-limited read and the output cut off mid-section). The `TrailController` body around lines 103/126 was not read — the actual branching logic for `/monthly` and its CSV-export path are not confirmed, only inferred from imports and constant usage.
- **DTO ownership crosses bounded contexts:** `TrailController` (in `ubm`) returns `chart`-owned DTOs (`MDHChart`, `BillExplainer`). Acceptable, but means schema changes in `chart` silently change the `/ubm/trail/monthly` contract.

## Recommended Next Steps

1. **Read the full `TrailController.java` body** (lines ~90–140) to confirm: (a) the exact path mapping for `/monthly`, (b) which `ChartService` method is invoked, (c) how `CSV_MONTHLY` branches request handling. The current analysis is grounded in imports and line-match positions only.
2. **Audit the public/internal split.** Compare `ChartController` vs. `PrivateChartController` route registrations and decide explicitly which controller owns any new monthly endpoint. Document the rule.
3. **Verify M2M scope wiring** by reading the security config (out-of-scope for this inventory) and confirming `read:spd.skalbox.trails` is the correct scope for monthly CSV exports — or whether a narrower `read:spd.skalbox.chart.monthly` scope would better follow least-privilege.
4. **Promote `/monthly` to a named abstraction** if changes are anticipated: extract a `MonthlyAggregationService` (or method group on `ChartService`) so the mode flag becomes a typed call rather than a string-driven branch. Reduces ripple risk across `ubm ↔ chart`.
5. **Pin the DTO contract.** Add a contract test (or OpenAPI snapshot) for the `/ubm/trail/.../monthly` response shape so downstream callers aren't broken by incidental changes in `chart/model/dto/MDHChart.java` or `BillExplainer.java`.
6. **Re-run the architecture pass with file-read permissions** so `ChartServiceImpl`, `MDHChart`, and `BillExplainer` can be inspected directly — the prior architect step truncated before completing its analysis.
