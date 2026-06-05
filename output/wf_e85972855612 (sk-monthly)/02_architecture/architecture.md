# Architecture

_Agent: `architect` (Software Architect)_  
_Status: `success` · attempts: 1_

---

Proceeding with the visible inputs (truncated `codebase_scan` content + file list). Where claims rely on the file list alone, I mark them as **inferred**.

---

# Architecture Analysis — `ChartController` Feature

## 1. Tech stack (evidence from imports)

| Concern | Evidence | Conclusion |
|---|---|---|
| Web layer | `reactor.core.publisher.Mono`, `ServerWebExchange`, `StepVerifier` | **Spring WebFlux (reactive)**, not Spring MVC |
| Test runtime | `@SpringBootTest(classes = {ChartController.class})`, `@MockitoBean` | Spring Boot 3.4+ (`@MockitoBean` is the new replacement for `@MockBean`) |
| Persistence | `io.spdigital.skalbox.data.redis.*` | Redis-backed repositories (no JPA visible in scope) |
| External system | `io.spdigital.skalbox.service.sap.SAPService` | SAP integration (likely the system of record for billing/MDH data) |
| Security | `io.spdigital.skalbox.web.common.security.SkalboxSecured` | Custom method-level security annotation |
| Scheduling | `io.spdigital.skalbox.chart.scheduler.TariffScheduler` | Spring `@Scheduled` job inside the feature module |

## 2. Module map of the `chart` feature

```
io.spdigital.skalbox.chart/
├── web.controller/
│   ├── ChartController            ← public-facing reactive endpoints
│   └── PrivateChartController     ← internal/admin endpoints (separated by audience)
├── service/
│   ├── ChartService     (interface)
│   └── ChartServiceImpl (impl)    ← business logic, orchestrates SAP + Redis
├── scheduler/
│   └── TariffScheduler            ← cron/periodic refresh of tariff data
├── model.dto/
│   ├── MDHChart  (with nested DailySKRequest, HourlySKRequest, MDHChartRequest, MDHChartResponse)
│   ├── BDLChart  (with nested Daily, Hourly + static factories like
│   │               BDLChart.Daily.Request.getDailyRequestForGraph(...))
│   ├── BillExplainer (nested SK.Request)
│   └── ChartConstants
└── exception/
    └── ChartApiException
```

External collaborators the feature pulls in:
- `data.redis.TariffRepository` (interface) + `TariffRepositoryImpl` — tariff cache
- `data.redis.UserAccountRepository`, `LogoutRepository` — session/auth state (likely via the security annotation pipeline)
- `auth.service.UserService` — user context resolution
- `service.sap.SAPService` — upstream SAP calls
- `web.common.security.SkalboxSecured` — auth/authorization aspect

## 3. Communication & layering

```
HTTP client
   │
   ▼
ChartController / PrivateChartController          (WebFlux, Mono<>)
   │  injects: ChartService, TariffScheduler(?), SAPService(?), TariffRepositoryImpl(?)
   ▼
ChartService (interface)  ──▶  ChartServiceImpl
   │
   ├──▶ SAPService              (outbound HTTP/RFC to SAP)
   ├──▶ TariffRepository        (Redis)
   ├──▶ UserService             (auth context)
   └──▶ DTO mappers in model.dto.BDLChart.*  (SK ⇄ BDL request shape conversion)

TariffScheduler ──▶ SAPService ──▶ TariffRepository   (background warm-up)

SkalboxSecured (AOP) ──▶ UserAccountRepository / LogoutRepository
```

All controller methods return `Mono<…>` (e.g. `chartController.monthly(exchange, monthlyReq)` returns `Mono<MDHChartResponse>`), so the call chain is non-blocking end-to-end **assuming** `SAPService` and the Redis repos expose reactive APIs — worth confirming.

DTO design: `MDHChart.*` represents the public "SK" contract; `BDLChart.*` represents the downstream "BDL" contract sent to SAP/JARVIS. Static factory `BDLChart.Daily.Request.getDailyRequestForGraph(dailySKRequest)` performs the SK→BDL translation.

## 4. Structural smells

| # | Smell | Evidence | Why it matters |
|---|---|---|---|
| **S1** | **Controller depends on `TariffRepositoryImpl` (concrete) and `TariffScheduler`** | `ChartControllerTest` declares `@MockitoBean TariffScheduler tariffScheduler;` and `@MockitoBean TariffRepositoryImpl tariffRepository;` and `@SpringBootTest(classes = { ChartController.class })` succeeds with these mocks | Two DIP violations: (a) injecting a `*Impl` instead of the `TariffRepository` interface defeats the abstraction that already exists in the same package; (b) a scheduler is a *time-driven* component — a request-driven controller should not call it. Suggests the controller is invoking scheduler methods imperatively (cache-warm / refresh-on-demand), which couples HTTP latency to scheduler internals. |
| **S2** | **Controller depends on `SAPService` directly** | Same test wires `@MockitoBean SAPService sapService;` for `ChartController` | Bypasses `ChartService`. The service layer is supposed to be the single seam to SAP; a controller talking to SAP directly leaks domain orchestration into the web layer and makes `ChartServiceImpl` a partial abstraction. |
| **S3** | **DTOs contain conversion logic** | `BDLChart.Daily.Request.getDailyRequestForGraph(dailySKRequest)`, `BDLChart.Hourly.Request.getHourlyRequestForGraph(hourlySKRequest)` | Anemic-DTO boundary is broken: a DTO in `model.dto` knows how to translate from a sibling DTO. This belongs in a dedicated mapper (`ChartRequestMapper` / MapStruct) under `service` or a `mapping` package. As more chart types are added, `BDLChart` will become a god DTO. |
| **S4** | **Controller has at least 4 direct collaborators visible in the test** | `ChartService`, `TariffScheduler`, `SAPService`, `TariffRepositoryImpl` (+ `ServerWebExchange`) | Approaching god-controller. A reactive WebFlux controller should typically depend only on one or two application-services. |
| **S5** | **Cross-feature reach into `data.redis` from the chart module** | Test imports `io.spdigital.skalbox.data.redis.TariffRepositoryImpl` from chart code | If `data.redis` is meant as shared infrastructure that's fine, but the chart feature's controller reaching into a specific Redis impl creates a structural dependency from `chart` → `data.redis` that should be expressed only through repository interfaces. |
| **S6** | **Two controllers, unclear boundary** | `ChartController` + `PrivateChartController` in the same `web.controller` package | "Private" appears to mean internal/admin endpoints. Verify they don't duplicate routes or share mutable state — and confirm `SkalboxSecured` is what distinguishes them rather than just package naming. |
| **S7** | **Potential blocking calls inside `Mono`** *(inferred — needs source verification)* | `TariffRepositoryImpl` is Redis-based; if it uses Jedis or Lettuce's sync API, calls inside a `Mono.fromCallable` without `subscribeOn(Schedulers.boundedElastic())` will block the event loop | Common WebFlux footgun; the test mocks hide this. |

## 5. Likely cyclic / coupling risks

No package cycle is observable from the file list alone, but the following are worth a static check (e.g. ArchUnit or `jdeps`):

- `chart.web.controller` → `chart.scheduler` → `chart.service` → `chart.scheduler`? (scheduler may call service which may call scheduler-managed cache; verify the scheduler doesn't depend on anything in `web.controller`).
- `chart.model.dto` should be a **leaf** package. The presence of `BDLChart.Daily.Request.getDailyRequestForGraph(MDHChart.DailySKRequest)` keeps it leaf-ish (DTO→DTO), but if any mapping pulls in `service` types, that's a cycle.

## 6. Recommendations (architectural, not stylistic)

1. **Remove `TariffScheduler` and `SAPService` from `ChartController`'s constructor.** Move on-demand cache-refresh behind `ChartService` (e.g. `chartService.refreshTariffIfStale()`); the controller should know nothing about scheduling or SAP.
2. **Depend on `TariffRepository` (interface), not `TariffRepositoryImpl`** — the interface already exists in the same package; switching is mechanical and restores DIP.
3. **Extract DTO conversion** into `chart.service.mapping.ChartRequestMapper` (MapStruct or hand-written). Keep `model.dto` strictly data-shape.
4. **Codify the controller↔service contract** with ArchUnit rules: "no class in `chart.web.controller` may depend on `chart.scheduler` or `service.sap` or `data.redis.*Impl`".
5. **Verify reactive purity of `TariffRepositoryImpl`** — if it's blocking, wrap with `Schedulers.boundedElastic()` or migrate to Lettuce reactive.
6. **Document the public/private split** — make `PrivateChartController`'s audience explicit through routing (`/internal/**`) and authorization (`@SkalboxSecured(role = …)`) rather than relying on class name alone.

## 7. Open questions for the next workflow step

- Are `ChartController` constructor params actually `TariffScheduler`/`SAPService`/`TariffRepositoryImpl`, or are those mocks left over from a refactor and now unused? (Source read of `ChartController.java` would confirm; the test alone can't distinguish.)
- Does `ChartServiceImpl` itself call `TariffScheduler`, or does the scheduler push state into a shared cache that the service reads?
- Is `SkalboxSecured` applied at controller class level or per method, and does `PrivateChartController` require a distinct role?

These three should be resolved before any refactor lands.
