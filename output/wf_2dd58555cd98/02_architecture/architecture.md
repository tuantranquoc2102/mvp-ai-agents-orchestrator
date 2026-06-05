# Architecture

_Agent: `architect` (Software Architect)_  
_Status: `success` · attempts: 1_

---

I was unable to read additional files (permission required), so this analysis is grounded in the truncated `TrailController.java` content, the file list, and package structure provided in `codebase_scan`.

# Architecture Analysis — `/monthly` Feature

## 1. Feature scope (evidence)

`/monthly` surfaces as **two endpoint match points in `TrailController.java`** (lines 103, 126) and is anchored to the constant `ChartConstants.CSV_MONTHLY` (imported at line 30). Visible code stops before the matched lines, but the surrounding controller plus the supporting files in the scan converge on a single pattern: **monthly aggregation/CSV-export endpoints under `/ubm/trail`, with the actual data-shaping work delegated to the `chart` module.**

Supporting evidence in the file list:
- `chart/web/controller/ChartController.java` + `PrivateChartController.java` — public vs. internal exposure of the same chart capability.
- `chart/service/ChartService(Impl).java` — chart business logic (+ tests).
- `chart/model/dto/MDHChart.java`, `BillExplainer.java` — monthly data-history / bill-explainer DTOs returned by chart endpoints.
- `chart/exception/ChartApiException.java` — module-local exception type.
- `ubm/controller/TrailController.java` — composes chart + smrd + account + trail services.

## 2. Layering

Classic Spring layered architecture, applied per bounded context:

```
HTTP (M2M-secured) ──► *Controller (web/controller)
                              │
                              ▼
                       *Service  ──► *ServiceImpl
                              │
                              ▼
                        DTOs (model/dto), domain exceptions
```

- **Web layer:** `*/web/controller/*` (chart) and `*/controller/*` (ubm). Annotated with `@RestController`, `@RequestMapping`, returns reactive `Mono`/`Flux`.
- **Service layer:** interface + `Impl` split (visible in `ChartService` / `ChartServiceImpl`, mirrored in the test set for `Account`, `SMRD`, `Payment`, `Refund`, `User`, `ProfileXtractor`).
- **DTO layer:** request/response objects co-located with their owning module (`chart/model/dto`, `ubm/dto`).
- **Cross-cutting:** `@Loggable` (custom AOP, package `io.spdigital.skalbox.logging`) and `@SkalboxM2MSecured(scopes = …)` from `web/common/security` — both applied consistently on every endpoint shown.

## 3. Modules (bounded contexts)

Top-level packages under `io.spdigital.skalbox.*` behave as bounded contexts:

| Module | Role in `/monthly` |
|---|---|
| `ubm` | Owns the `/ubm/trail/**` HTTP surface; orchestrates the call. |
| `chart` | Owns the monthly chart/CSV computation, DTOs (`MDHChart`, `BillExplainer`), errors. Has **two controllers** (public + private). |
| `smrd` | Meter-reading retrieval/submission. Pulled in by `TrailController` (likely feeds monthly aggregation). |
| `accounts` | Account lookup/validation. |
| `auth` | Auth0 integration (`Auth0ServiceImpl`) — not on the request path of `/monthly` directly but appears in feature-scoped scan, suggesting principal resolution or shared security plumbing. |
| `web/common/security` | `@SkalboxM2MSecured` — shared OAuth2/M2M scope check. |
| `logging` | `@Loggable` cross-cutting logger. |

Other modules in the scan (`payment`, `refund`, `profilextractor`) appear only as *test* files — they are not on the `/monthly` runtime path; they were included by the scan because tests share helpers/fixtures with the chart/account stack.

## 4. Communication & runtime style

- **Reactive end-to-end:** Project Reactor (`Mono`, `Flux`). `Flux<ResponseCsv>` is used for CSV streaming (`/pub/csv` pattern) — by analogy, `/monthly` CSV is almost certainly a `Flux` stream too (consistent with the `CSV_MONTHLY` constant).
- **Synchronous in-process composition:** Controllers wire services via constructor injection (`@RequiredArgsConstructor` + `final` fields). No event bus, no message broker visible in the scoped files.
- **Security:** Machine-to-machine bearer-token model, scope-gated per endpoint (`read:spd.skalbox.trails` for every method shown).
- **External integrations** implied by sibling services: Auth0 (`Auth0ServiceImpl`) and an upstream SMRD/UBM system feeding meter readings & subscriptions.

## 5. Structural smells

1. **Cross-context controller composition.** `TrailController` (in `ubm`) injects `ChartService`, `SMRDService`, **and** `AccountService` directly. The web layer is acting as an orchestrator across three bounded contexts — a thin application-service / use-case layer is missing. Any change to how monthly trails are assembled forces churn in a controller and risks scope creep on `ubm`. Recommend a `MonthlyTrailUseCase` (or `TrailApplicationService`) in `ubm/service` that owns the composition and leaves the controller as a pure HTTP adapter.

2. **Constant in `chart` driving behaviour in `ubm`.** `TrailController` imports `ChartConstants.CSV_MONTHLY`. This is a small coupling leak from `chart` into `ubm`'s web layer — the controller is making a chart-format decision. Push this into `ChartService` (e.g. `chartService.monthlyCsv(...)`) so `ubm` no longer needs to know chart format identifiers.

3. **Two chart controllers, one service.** `ChartController` + `PrivateChartController` both presumably delegate to `ChartServiceImpl`. Without visibility into the routes it's a *potential* smell rather than confirmed: watch for divergent auth/validation logic between the two controllers — if any business rule lives only in one, that's a duplication risk. A shared request-mapper/validator would mitigate.

4. **No visible cycles**, but `ubm → chart`, `ubm → smrd`, `ubm → accounts` form a star with `ubm` at the centre. Acceptable as long as `chart`/`smrd`/`accounts` do **not** import from `ubm`. Worth a one-line `ArchUnit` rule to enforce.

5. **Test fan-out hints at shared fixtures.** Tests for `payment`, `refund`, `profilextractor`, `security` surfaced in a `/monthly`-scoped scan. Either the search matched a generic `monthly` token in fixtures, or these tests transitively touch chart code via shared base classes. If the latter, the test base is a god-fixture and should be split per module.

## 6. Open questions the next workflow step should resolve

- Exact HTTP method, path suffix, and return type of the two `/monthly` matches (lines 103 & 126 of `TrailController`) — current file content was truncated before reaching them.
- Whether `/monthly` exists **only** in `TrailController`, or whether `ChartController` / `PrivateChartController` also expose a `/monthly` route (the scan flagged the files but no line numbers were given for them in the visible portion).
- Whether `MDHChart` is the response DTO for `/monthly` (name suggests "Monthly Data History") or is consumed only internally.
- Source of monthly data: derived from `SMRDService` meter readings, from an upstream UBM call, or both joined in `ChartServiceImpl`.

Resolving (1) and (2) requires reading `TrailController` past line 100 and grepping `/monthly` across the two chart controllers — both blocked by the current permission scope.
