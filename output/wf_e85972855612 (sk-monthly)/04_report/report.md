# Report

_Agent: `assistant` (General Assistant)_  
_Status: `success` · attempts: 1_

---

# ChartController Feature — Final Analysis Report

**Prepared for:** Engineering Lead
**Scope:** `io.spdigital.skalbox.chart.*` (20 Java files, ~337 KiB) in `skalbox-api`
**Date:** 2026-06-04

---

## 1. Overview

`ChartController` is the public HTTP entry point for the `chart` feature module of the Skalbox API — a Spring Boot 3.4+ / WebFlux reactive service that exposes monthly, daily, hourly, and bill-explainer chart data sourced from a downstream SAP system and cached/augmented via Redis. The feature is delivered in a single language (Java, 20/20 files) and follows a clean, conventional Spring layout: controllers → service interface + impl → DTOs → integrations.

Two HTTP entry points segment the surface area by audience:
- `chart/web/controller/ChartController.java` — public/standard consumer endpoints.
- `chart/web/controller/PrivateChartController.java` — privileged/internal endpoints, protected by `web/common/security/SkalboxSecured.java`.

A secondary, non-HTTP entry point — `chart/scheduler/TariffScheduler.java` — periodically refreshes tariff state in Redis (`data/redis/TariffRepository(+Impl).java`), keeping chart computations off the SAP hot-path where possible.

Test coverage at the feature level is healthy in surface (8 tests including `ChartControllerTest`, `PrivateChartControllerTest`, `ChartServiceImplTest`, `TariffRepositoryImplTest`); depth is not assessable from the inventory alone.

---

## 2. Architecture

### Layering

```
chart/
├── web/controller/        → ChartController, PrivateChartController (WebFlux handlers)
├── service/               → ChartService (interface) + ChartServiceImpl (orchestration)
├── scheduler/             → TariffScheduler (periodic tariff refresh)
├── model/dto/             → BDLChart (+ MDHChart, BillExplainer, ChartConstants — out of scan)
└── (exception)            → ChartApiException (referenced by tests; out of scan)
```

External collaborators referenced from within the feature:
- **SAP integration:** `service.sap.SAPService` — system of record for billing/MDH data.
- **Redis caches/state:** `data/redis/TariffRepository(+Impl).java`, `data/redis/UserAccountRepository(+Impl).java`, `data/redis/LogoutRepository(+Impl).java`.
- **Auth:** `auth/service/UserService.java` + `web/common/security/SkalboxSecured.java` (custom method-level security).

### Programming model

Reactive end-to-end. Evidence from `ChartControllerTest`: `ServerWebExchange`, `Mono`, `reactor.test.StepVerifier`. Spring Boot 3.4+ confirmed by use of `@MockitoBean` (the post-3.4 replacement for `@MockBean`).

### Operations exposed (inferred from test fixtures)

- `monthly(...)` — `MDHChart.MDHChartRequest` → `MDHChartResponse`, aggregating premise + consumption-year data.
- Daily and hourly chart variants (`BDLChart.Daily.Request.getDailyRequestForGraph(...)`, hourly equivalents, plus parallel SK request shapes on `MDHChart`).
- Bill Explainer (`BillExplainer.SK.Request`).

### Boundary separation

The split between `ChartController` and `PrivateChartController` (different controller classes rather than path-prefixed routes on one class) is the right call — it makes the security boundary structurally visible and keeps `SkalboxSecured` concentrated on the privileged surface. The `chart` package is internally cohesive (web → service → DTO → scheduler) and depends outward only on `auth`, `data.redis`, and `service.sap` — a clean dependency direction with no obvious cycles in scope.

---

## 3. Quality & Risk

### Strengths
- **Clean module shape.** Interface + impl on the service layer (`ChartService` / `ChartServiceImpl`) leaves the seam open for testing and substitution. Controllers are thin handlers per the test fixtures.
- **Reactive consistency.** No mix of blocking `RestController` patterns observed — the feature appears uniformly WebFlux.
- **Test breadth.** Dedicated tests at every layer touched: controller (public + private), service impl, repository impl, and adjacent `UserService`/`SMRDService`. This is above-average for a feature module.
- **Cache-first design for tariffs.** `TariffScheduler` + `TariffRepository` decouple chart latency from SAP availability for the tariff dimension.

### Risks & concerns

1. **SAP is on the critical path** for non-tariff data (monthly/daily/hourly aggregations, bill explainer). The inventory shows no circuit-breaker, retry policy, or timeout configuration in scope. A slow or failing `SAPService` will propagate as `ChartApiException` to clients — needs resilience inspection (`service.sap.SAPService` is out of the 20-file scan and must be pulled in to confirm).
2. **Reactive correctness is unverified.** Blocking calls inside a `Mono` chain — e.g. synchronous Redis clients or blocking SAP SDK calls in `ChartServiceImpl` — would stall WebFlux worker threads. The scan does not include `ChartServiceImpl` body or the Redis impls' I/O strategy; this is the single highest-impact thing to audit.
3. **Security surface depends on an annotation we can't see.** `SkalboxSecured` is custom (`web/common/security/SkalboxSecured.java`). The privileged `PrivateChartController` is only as safe as that annotation's pointcut/aspect implementation. Worth a focused read.
4. **DTO factory methods on request types.** `BDLChart.Daily.Request.getDailyRequestForGraph(...)` style indicates request-building logic lives on the DTOs themselves. This is fine in moderation but tends to grow into hidden business rules; needs a look at `chart/model/dto/BDLChart.java` and the (out-of-scan) `MDHChart`/`BillExplainer`/`ChartConstants`.
5. **Inventory blind spots.** No `pom.xml`/`build.gradle`, no `application*.yml`, and no `@SpringBootApplication` bootstrap class in scope — meaning **process-level** entry points, dependency versions, and runtime configuration (timeouts, Redis pool sizes, scheduler cron expressions) are not visible. The feature-level entry points (`ChartController`, `PrivateChartController`, `TariffScheduler`) are identified, but operational tuning cannot be assessed from this slice.
6. **`LogoutRepository` coupling in a chart feature is unusual.** Its presence among the referenced collaborators suggests session-invalidation checks run inside the chart request path. If true, that's an extra Redis round-trip per chart call — worth confirming it isn't redundant with what `SkalboxSecured` already does.

### Severity ranking
| # | Risk | Severity |
|---|---|---|
| 2 | Possible blocking I/O in reactive chain | **High** |
| 1 | No visible SAP resilience policy | **High** |
| 3 | Custom security annotation not yet inspected | Medium |
| 6 | Logout check on chart hot path | Medium |
| 4 | Business logic creeping into DTOs | Low |
| 5 | Config/build files outside scan | Low (scoping artifact) |

---

## 4. Recommended Next Steps

In priority order:

1. **Audit `ChartServiceImpl` for reactive correctness.** Pull `chart/service/ChartServiceImpl.java`, `data/redis/TariffRepositoryImpl.java`, `data/redis/UserAccountRepositoryImpl.java`, `data/redis/LogoutRepositoryImpl.java`, and `service/sap/SAPService` (currently out of scan). Confirm: (a) no `.block()` calls, (b) blocking clients are wrapped with `Mono.fromCallable(...).subscribeOn(Schedulers.boundedElastic())`, (c) reactive Redis (Lettuce reactive API) is used where possible.
2. **Add/verify resilience around SAP.** Look for Resilience4j or Spring Cloud Circuit Breaker annotations on `SAPService`. If absent, introduce a timeout + circuit breaker + bounded retry, with a graceful degraded response from `ChartController` for non-critical chart variants.
3. **Read `web/common/security/SkalboxSecured.java` end-to-end.** Validate the aspect/interceptor handles missing/invalid principals safely, and confirm it is actually applied on every handler method of `PrivateChartController.java`.
4. **Clarify the `LogoutRepository` role on the chart path.** If it's a session-revocation check, ensure it is either part of `SkalboxSecured` (single check) or explicitly justified per endpoint — don't pay for it twice.
5. **Bring config into scope for a follow-up review.** Re-run the inventory without the `feature_query="ChartController"` filter (or with an additional pass) to capture `pom.xml`/`build.gradle`, `application*.yml`, and the `@SpringBootApplication` class. Specifically check: WebFlux Netty thread counts, Redis pool sizing, `TariffScheduler` cron, and SAP client timeouts.
6. **Fetch and review the out-of-scan DTO types.** `MDHChart`, `BillExplainer`, `ChartConstants`, and the full body of `chart/model/dto/BDLChart.java` — confirm request-factory methods (e.g. `BDLChart.Daily.Request.getDailyRequestForGraph(...)`) are pure mappers, not hiding domain rules that belong in `ChartServiceImpl`.
7. **Assess test depth, not just count.** The 8 tests cover the right classes; spot-check `ChartControllerTest.java` and `ChartServiceImplTest.java` to confirm they exercise error paths (SAP failure, Redis miss, auth failure) in addition to happy paths via `StepVerifier`.
8. **Document the public vs. private contract.** A short README in `chart/` describing which operations are on `ChartController` vs. `PrivateChartController`, plus the `SkalboxSecured` semantics, would reduce future drift between the two controllers.

---

**Bottom line:** The `ChartController` feature has a clean, conventional, reactive Spring shape with sensible layer separation and above-average test breadth. The two highest-leverage follow-ups — and the only items I would block a release on without further evidence — are **(a) confirming no blocking I/O leaks into the reactive pipeline** and **(b) confirming SAP failure modes are bounded**. Everything else is incremental hardening.
