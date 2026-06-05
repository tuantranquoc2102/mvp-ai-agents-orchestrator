# Report

_Agent: `assistant` (General Assistant)_  
_Status: `success` · attempts: 1_

---

# Final Analysis Report — Feature `/customer`

**Project:** `ubm-api` (SP Digital — User/Billing Management) · **Scope:** 3 Java files matched, ~22 KB · **Stack:** Spring WebFlux + Project Reactor + Lombok + Jackson

---

## Overview

The `/customer` feature exposes administrative read-side operations over customer records held in SAP back-end systems. The HTTP surface is intentionally narrow — two endpoints on `AdminController` (`src/main/java/io/spdigital/ubm/admin/controller/AdminController.java`):

- **`GET /admin/customers`** (line 36) — paginated search; parameters: `type`, `searchString`, `pageNumber`, `pageSize`, `direction`; returns `Mono<Yggdrasil.SearchCustomers.Response>`.
- **`GET /admin/customer`** (line 46) — single customer lookup by `bpNo` and `userId`; returns `Mono<GetCustomerResponse>`.

Both endpoints are reactive (`Mono<T>`), instrumented with the project-local `@Loggable` aspect (`io.spdigital.ubm.logging`), and rely on default pagination/sort constants from `io.spdigital.ubm.common.Constants`. The controller delegates to an `AdminService` (not in the filtered slice), which fans out to SAP via the integration contract in `service/sap/po/SAP.java`. Authorization is enum-driven through `common/enums/Permission.java`. No build descriptor, test, or `application.yml` was in scope, so configuration and gating wiring must be confirmed out-of-band.

---

## Architecture

**Layering (as evidenced by the three in-scope files):**

```
HTTP (Spring WebFlux)
  └─ AdminController (@RestController, base /admin)
        │  @Loggable, Mono<…>
        ▼
  AdminService  ← not in scope; orchestration assumed here
        │
        ▼
  SAP integration layer (SAP.java — "PO" = Protocol Object)
        ├─ /CustomerDetailsRetrieval         (EBS_CUSTOMER_DETAILS_RETRIEVAL, line 20)
        ├─ /MSSLCustomerDetailsRetrieval     (MSSL_CUSTOMER_DETAILS_RETRIEVAL, line 22)
        └─ /CustomerProfileRetrieval         (CUSTOMER_PROFILE_RETRIEVAL, line 26)

Cross-cutting:
  • Permission.java  → authorization enum (gating mechanism not visible in slice)
  • MaskingUtil      → PII masking on SAP responses
  • Jackson @JsonNaming(SnakeUpperCaseStrategy) → SAP wire format (SCREAMING_SNAKE_CASE)
```

**Key architectural observations:**

1. **Fully reactive pipeline.** Controller returns `Mono<T>`, so the downstream `AdminService` → SAP client chain must also be non-blocking end-to-end (likely `WebClient`). Any blocking JDBC or RestTemplate call inside `AdminService` would silently degrade the event loop.
2. **Three distinct SAP endpoints back the customer surface** (EBS, MSSL, Profile). The controller has only two methods, so `AdminService` is doing routing/composition — probably switching by customer `type` for search, and aggregating profile + details for the single-lookup case.
3. **DTO convention is consistent and disciplined.** Nested `*.Request` / `*.Response` types under domain namespaces (`Yggdrasil.SearchCustomers.Response`, `Subscription.Update.Request`) keep transport contracts colocated and discoverable.
4. **`SAP.java` as an `interface` of constants + DTOs** is an idiomatic-Java-but-aging pattern. It works, but mixes URL routing, payload shape, and JSON naming policy into a single file (~15 KB) — a refactor candidate as the SAP surface grows.
5. **Authorization is enum-based, not annotation-based at the controller** (no `@PreAuthorize` visible on the methods in scope). Either a custom security filter consumes `Permission`, or the gate lives in `AdminService`. This needs verification — controller-level enforcement is missing from the visible code.

---

## Quality & Risk

| Area | Risk | Evidence / Notes |
|---|---|---|
| **Authorization placement** | 🟠 Medium-High | Neither `GET /admin/customers` nor `GET /admin/customer` carries a visible `@PreAuthorize` / permission annotation in `AdminController.java` (lines 36, 46). If gating lives only inside `AdminService`, defense-in-depth is weaker and easy to bypass on future endpoints copied from this template. |
| **PII exposure** | 🟠 Medium | `MaskingUtil` is referenced in the SAP layer, confirming PII is in flight. Coverage of masking across all three SAP endpoints (`/CustomerDetailsRetrieval`, `/MSSLCustomerDetailsRetrieval`, `/CustomerProfileRetrieval`) is not provable from the slice. `@Loggable` on the controller methods is a risk if it logs request/response bodies that contain BP numbers or user IDs. |
| **Reactive integrity** | 🟠 Medium | Cannot confirm from scope that the SAP client is non-blocking. A blocking call inside a `Mono` chain (without `subscribeOn(boundedElastic())`) will stall the Netty event loop under load. |
| **Test coverage** | 🔴 High (unknown) | Zero test files matched the filter. For an admin endpoint touching three SAP integrations and PII, the absence is concerning until confirmed otherwise. |
| **Input validation** | 🟠 Medium | `searchString`, `bpNo`, `userId` are passed straight through. No `@Validated` / `@Pattern` visible. Unbounded `pageSize` (if the default constant is large) is a DoS lever against SAP. |
| **Error handling** | 🟡 Low-Medium | Not visible in scope. WebFlux requires explicit `onErrorResume` / global `@ControllerAdvice` to avoid leaking SAP errors to admin clients. |
| **Coupling to SAP wire format** | 🟡 Low | `SnakeUpperCaseStrategy` is centralized in `SAP.java`, which is good. The interface-as-container pattern, however, will become unwieldy as more SAP operations are added. |
| **Observability** | 🟢 Low | `@Slf4j` + `@Loggable` AOP is in place. Trace context propagation across the reactive chain to SAP should be verified (Reactor context vs. MDC). |
| **API contract stability** | 🟡 Low-Medium | Returning the SAP-derived `Yggdrasil.SearchCustomers.Response` directly couples the public admin API to an internal/domain DTO namespace. Renaming `Yggdrasil` later becomes a breaking change. |

---

## Recommended Next Steps

**1. Verify and harden authorization (this week).**
Confirm where `Permission` is consumed. If it's not enforced at the controller, add explicit `@PreAuthorize("hasAuthority('...')")` (or the project's equivalent) on both methods in `AdminController.java` (lines 36 and 46). Defense-in-depth: keep service-layer checks too.

**2. Audit `@Loggable` output for PII.**
Inspect the `io.spdigital.ubm.logging` aspect. If it serializes request/response bodies, ensure `bpNo`, `userId`, and any field flowing back from `/CustomerProfileRetrieval` go through `MaskingUtil` before the log sink. Add an explicit allow/deny field list rather than relying on developer discipline.

**3. Prove the chain is non-blocking.**
Open `AdminService` and the SAP client. Confirm `WebClient` (not `RestTemplate`) and that no `.block()` calls exist on the request path. Add a Reactor BlockHound check in test scope to make regressions loud.

**4. Add request validation and bound pagination.**
On `GET /admin/customers`, validate `searchString` length, constrain `pageSize` to a sensible cap (e.g., ≤100), and whitelist `type` / `direction`. On `GET /admin/customer`, validate `bpNo` format. Use `@Validated` + JSR-380 annotations on a request record.

**5. Introduce an integration test layer.**
At minimum: `@WebFluxTest` slices for `AdminController` covering happy path, auth-denied, validation failure, and SAP error propagation; WireMock for the three SAP endpoints declared in `SAP.java` (lines 20, 22, 26). Treat absence of any `/customer` tests as a release blocker.

**6. Decouple the public response shape from `Yggdrasil`.**
Introduce dedicated admin-API response DTOs and map from `Yggdrasil.SearchCustomers.Response` inside the controller (or a thin mapper). Protects the external contract from internal refactors.

**7. Plan the `SAP.java` refactor (next quarter, not urgent).**
Split the interface-of-constants into (a) a `SapEndpoints` constants class, (b) per-operation DTO files under `service/sap/po/customer/`, and (c) a single Jackson config bean for `SnakeUpperCaseStrategy`. The current ~15 KB single file will keep growing and will become a merge-conflict hotspot.

**8. Confirm out-of-scope artifacts exist and are healthy.**
The filtered slice contains no `pom.xml`/`build.gradle`, no `application.yml`, and no tests for `/customer`. Before signing off, verify: SAP base URLs and timeouts are externalized, circuit-breaker / retry policy exists on the SAP client (Resilience4j is the usual choice in this stack), and metrics for the three SAP calls are exported.

---

**Bottom line:** The `/customer` slice is small, idiomatic, and reactive — a clean foundation. The material risks are not in what's written but in what isn't visible from the slice: authorization enforcement at the edge, PII handling in logs, blocking calls hiding in `AdminService`, and the test gap. Address items 1–5 before treating this surface as production-hardened.
