# Inventory

_Agent: `researcher` (Research Specialist)_  
_Status: `success` · attempts: 1_

---

# ChartController Feature — Codebase Inventory

## Scope & Size
- **Project root:** `F:\02_SPG_PROJECTS\skalbox-api`
- **Files matched to feature:** 20
- **Total bytes:** ~345 KB (337 KiB)
- **Language distribution:** 100% Java (20/20 files) — single-language scope, no polyglot concerns.

## File Composition (ChartController-relevant only)

| Layer | Files |
|---|---|
| **Web / Controllers (entry points)** | `chart/web/controller/ChartController.java`, `chart/web/controller/PrivateChartController.java` |
| **Service layer** | `chart/service/ChartService.java` (interface), `chart/service/ChartServiceImpl.java` |
| **Scheduling** | `chart/scheduler/TariffScheduler.java` |
| **DTO / Model** | `chart/model/dto/BDLChart.java` (BDL = downstream chart payload; references `MDHChart`, `BillExplainer`, `ChartConstants` not in scan) |
| **Data / Redis** | `data/redis/TariffRepository(+Impl).java`, `LogoutRepository(+Impl).java`, `UserAccountRepository(+Impl).java` |
| **Auth / Security** | `auth/service/UserService.java`, `web/common/security/SkalboxSecured.java` |
| **Tests (8)** | `ChartControllerTest`, `PrivateChartControllerTest`, `ChartServiceImplTest`, `SMRDServiceImplTest`, `TariffRepositoryImplTest`, `UserServiceImplTest` |

## Likely Entry Points
- **HTTP controllers (primary):** `ChartController` (public/standard endpoints) and `PrivateChartController` (privileged/internal endpoints) — both in `io.spdigital.skalbox.chart.web.controller`.
- **Scheduled trigger:** `TariffScheduler` — secondary, non-HTTP entry point driving tariff refresh used by the chart pipeline.

## Architectural Signals (from `ChartControllerTest`)
- **Framework:** Spring Boot (`@SpringBootTest`, `@MockitoBean`, `@Autowired`).
- **Programming model:** Reactive — Spring WebFlux (`ServerWebExchange`, `Mono`, `reactor.test.StepVerifier`).
- **Package root:** `io.spdigital.skalbox` — Maven/Gradle standard layout (`src/main/java`, `src/test/java`).
- **External integrations referenced:** `SAPService` (SAP backend), Redis repositories (`TariffRepositoryImpl`), domain exception `ChartApiException`.
- **Test stack:** JUnit 5 + Mockito + Reactor Test.

## Notable Operations Exposed (inferred from test setup)
- `monthly(...)` → `MDHChart.MDHChartRequest` → `MDHChartResponse` (premise + consumption-year aggregation)
- Daily and hourly chart endpoints (SK + BDL request variants)
- Bill Explainer endpoint (`BillExplainer.SK.Request`)

## Config / Build Files
**Not present in the pre-filtered scan.** The `feature_query="ChartController"` filter excluded top-level build/config files (`pom.xml`/`build.gradle`, `application.yml`, etc.). Spring Boot + WebFlux + Redis + Reactor are evidenced by imports, but the actual build descriptor and runtime config are outside this 20-file slice and would need a separate scan to confirm.

## Gaps Worth Flagging to Next Steps
- Several referenced types are **not in the scan** and may need fetching for full analysis: `MDHChart`, `BillExplainer`, `ChartConstants`, `ChartApiException`, `SAPService`, `PrivateChartController` body, `ChartController` body, `ChartServiceImpl` body.
- No build file, no `application*.yml`, no main `@SpringBootApplication` class is included — entry-point identification above is **feature-level** (HTTP handler classes), not **process-level** (the `main()` bootstrap class).
