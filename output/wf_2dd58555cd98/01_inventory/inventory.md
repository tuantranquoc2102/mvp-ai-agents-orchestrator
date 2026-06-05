# Inventory

_Agent: `researcher` (Research Specialist)_  
_Status: `success` · attempts: 1_

---

# `/monthly` Feature — Codebase Inventory

## Language & Size
- **Languages:** 100% Java (20/20 files)
- **Total size:** ~695 KB (695,131 bytes)
- **Test coverage footprint:** 9 of 20 files are tests (`src/test/...`), suggesting the feature is exercised by existing unit tests rather than greenfield.

## Module/Package Layout (feature-scoped)
The matched files cluster into a handful of bounded contexts under `io.spdigital.skalbox`:

| Package | Role in `/monthly` |
|---|---|
| `ubm.controller` | `TrailController` — primary HTTP entry, mounted at `/ubm/trail` |
| `chart.web.controller` | `ChartController`, `PrivateChartController` — chart/billing endpoints |
| `chart.service` | `ChartService` / `ChartServiceImpl` — core charting logic (likely owner of monthly aggregation) |
| `chart.model.dto` | `MDHChart`, `BillExplainer` — DTOs returned by monthly endpoints |
| `chart.exception` | `ChartApiException` — feature-specific error type |
| `auth.service` | `Auth0ServiceImpl` — Auth0 token/identity resolution used by secured endpoints |
| `accounts.service` | `AccountServiceImpl` — account lookup tied to monthly views |

Adjacent services appearing only in tests (`smrd`, `profilextractor`, `payment`, `refund`, `security`) indicate `/monthly` is integration-tested against neighboring domains but does not own code in them.

## Likely Entry Points
1. **`TrailController`** (`/ubm/trail/...`) — explicit `/monthly` references at lines 103 & 126; uses `ChartConstants.CSV_MONTHLY` to drive CSV export branching. Secured with `@SkalboxM2MSecured(scopes = "read:spd.skalbox.trails")`.
2. **`ChartController` / `PrivateChartController`** — chart-facing REST endpoints; the implementation flows through `ChartServiceImpl`.

## Framework & Conventions (inferred from the matched files)
- **Spring WebFlux (reactive):** `Mono<T>` / `Flux<T>` return types, `@RestController`, `@GetMapping`, `@RequestParam`.
- **Lombok:** `@RequiredArgsConstructor`, `@Slf4j` — constructor injection is the norm.
- **Custom cross-cutting annotations:**
  - `@Loggable` (`io.spdigital.skalbox.logging.Loggable`) — request/response logging.
  - `@SkalboxM2MSecured` (`io.spdigital.skalbox.web.common.security.SkalboxM2MSecured`) — machine-to-machine OAuth scope enforcement.
- **Date handling:** `LocalDate` with `@DateTimeFormat(iso = ISO.DATE)` for query params.
- **Constants centralization:** `ChartConstants.CSV_MONTHLY` (in `chart.model.dto`) is the canonical token distinguishing monthly from other granularities — a likely branching point for the feature.

## Config / Build Files
None present in the feature-scoped slice (scan was pre-filtered to files referencing `/monthly`). Build descriptors (`pom.xml` / `build.gradle`), `application.yml`, and security config are **out of scope** for this inventory; investigate them separately if dependency or wiring questions arise.

## Notable Observations for Downstream Work
- `/monthly` is not its own controller — it is a **route fragment / mode flag** inside `TrailController` (two hits) plus the `CSV_MONTHLY` constant. Expect changes to ripple through `TrailService` ↔ `ChartService` boundaries.
- The presence of both `ChartController` and `PrivateChartController` implies a **public vs. internal** split worth confirming before adding new monthly endpoints.
- Auth path is **M2M-scoped**, not end-user JWT — any new `/monthly` route must declare an appropriate `read:spd.skalbox.*` scope.
