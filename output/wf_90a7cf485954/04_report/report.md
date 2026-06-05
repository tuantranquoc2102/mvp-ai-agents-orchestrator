# Report

_Agent: `assistant` (General Assistant)_  
_Status: `success` · attempts: 1_

---

# `/customer` Feature — Engineering Analysis Report

## Overview

The `/customer` feature in `ubm-api` (SP Digital's UBM — User/Billing Management service, package root `io.spdigital.ubm`) exposes admin-facing customer read APIs backed by SAP integrations. The pre-filtered scope contains **3 Java files (~22 KB)** built on **Spring WebFlux** (reactive `Mono<…>` responses) with **Lombok**, **Jackson** (mixed `com.fasterxml.jackson` and `tools.jackson.databind` namespaces), and a custom `SnakeUpperCaseStrategy` for SAP payload (de)serialization.

Two endpoints, both nested under `/admin`, surface the feature:

| Method | Path | Handler (file:line) | Returns |
|---|---|---|---|
| `GET` | `/admin/customers` | `AdminController.getCustomers` (`src/main/java/io/spdigital/ubm/admin/controller/AdminController.java:36`) | `Mono<SearchCustomers.Response>` |
| `GET` | `/admin/customer` | `AdminController.getCustomer` (`src/main/java/io/spdigital/ubm/admin/controller/AdminController.java:46`) | `Mono<GetCustomerResponse>` |

Authorization is gated via a `Permission` enum constant (`src/main/java/io/spdigital/ubm/common/enums/Permission.java`) and every endpoint is decorated with a custom `@Loggable` AOP annotation from `io.spdigital.ubm.logging`. Downstream reads land on SAP via constants declared in `src/main/java/io/spdigital/ubm/service/sap/po/SAP.java` (`/CustomerDetailsRetrieval` L20, `/MSSLCustomerDetailsRetrieval` L22, `/CustomerProfileRetrieval` L26, plus the write-side `/UpdateBillPreference` L24 that is *not* exposed under this feature's HTTP surface).

## Architecture

**Layering (classic 3-layer reactive Spring):**
```
HTTP edge (AdminController, WebFlux)
        │ Mono<…>
        ▼
Application service (AdminService — not in scope, inferred from imports)
        │
        ├─► SAP integration (service.sap.po.SAP)  — system of record
        └─► Yggdrasil model DTOs (model.dto)      — shared identity/user namespace
```

**Key observations from scope:**

- **Controller is thin.** `AdminController` is a `@RequiredArgsConstructor`/`@Slf4j` Spring `@RestController` mapped at `/admin`. It accepts query params (`bpNo`, `userId` for the single read; `type`, `searchString`, `pageNumber`, `pageSize`, `direction` for search) and delegates straight to `AdminService`. Pagination defaults come from `io.spdigital.ubm.common.Constants`.
- **DTO surface.** `GetCustomerResponse`, `Yggdrasil.SearchCustomers`, `Subscription`, and `UpdateBpNo` are referenced from `io.spdigital.ubm.admin.dto` / `io.spdigital.ubm.model.dto`. The `Yggdrasil` namespace appears to be a shared, organisation-wide identity model.
- **SAP integration contract is constant-driven.** `SAP.java` is the canonical place where downstream endpoint paths live, alongside a DTO interface and (per the inventory) a custom `SnakeUpperCaseStrategy` Jackson naming convention used to bridge SAP's `SNAKE_UPPER_CASE` payloads to Java conventions. `MaskingUtil` is referenced from SAP DTOs, indicating PII masking is wired at the integration boundary.
- **Cross-cutting concerns are centralised.** `@Loggable` AOP, the shared `Constants` class, and the `Permission` enum keep logging, defaults, and RBAC out of the controller body.
- **Reactive end-to-end.** Both endpoints return `Mono<…>` and there is no blocking call visible in scope; the reactive contract appears to continue into `AdminService` and the SAP client.

**Out of scope but architecturally relevant (gaps in this audit):**
- `AdminService.getCustomer(...)` — the business orchestration is not visible.
- `SAP.java` was truncated (~20 KB additional content); full request/response DTO shapes for `CustomerDetailsRetrieval` / `MSSLCustomerDetailsRetrieval` / `CustomerProfileRetrieval` were not inspected.
- `Permission.java` body was truncated — the exact RBAC constant used to gate these endpoints is not confirmed.
- No build files (`pom.xml`/`build.gradle`), no `application.yml`, no `Dockerfile`, no CI config matched the `/customer` filter, so resilience, timeouts, connection-pool, and security configuration for the SAP client are invisible here.

## Quality & Risk

**Strengths**
- Clean separation: controller → service → SAP boundary, with cross-cutting concerns isolated (Logging AOP, shared Constants, Permission enum, MaskingUtil).
- End-to-end reactive stack avoids thread-pool exhaustion under SAP latency, *provided* the SAP client itself is non-blocking (not verified in scope).
- Integration endpoints are not hard-coded at call sites — `SAP.java` is the single source of truth.

**Risks / smells**

1. **Mixed Jackson namespaces.** Inventory flags both `com.fasterxml.jackson` and the newer `tools.jackson.databind` namespace in play (`src/main/java/io/spdigital/ubm/service/sap/po/SAP.java`). Running two Jackson generations side-by-side typically means duplicate configuration (modules, naming strategies, mappers) and is a frequent source of subtle serialization bugs. Confirm whether this is a deliberate migration or accidental drift.
2. **GET with `userId` in query string.** `GET /admin/customer?bpNo=…&userId=…` (`AdminController.java:46`) exposes both the business partner number and a user identifier in URLs, which propagate to access logs, proxies, and APM traces. Even with `MaskingUtil` on response payloads, the **request** side is unmasked. Consider header- or POST-body-borne identifiers for sensitive lookups, or guarantee URL scrubbing in the logging pipeline.
3. **Authorization not visible in the controller.** The `Permission` enum exists (`src/main/java/io/spdigital/ubm/common/enums/Permission.java`) but the controller in scope shows no `@PreAuthorize` or equivalent annotation in the matched lines. The gating mechanism (filter? service-layer check? method security?) must be confirmed — admin customer reads are a high-value target.
4. **Two near-identical search paths into SAP.** `EBS_CUSTOMER_DETAILS_RETRIEVAL` and `MSSL_CUSTOMER_DETAILS_RETRIEVAL` (`SAP.java:20,22`) suggest customer-type branching (EBS vs MSSL business lines). Routing logic lives in `AdminService` (out of scope) and is a likely place for hidden complexity, duplicated mapping, and divergence over time.
5. **Singular/plural endpoint pair is REST-awkward.** `/admin/customer` (singleton) and `/admin/customers` (collection) under the same controller is unusual; conventional REST would use `/admin/customers/{bpNo}`. The current shape forces query-string identification of a single resource and makes caching/CDN keys harder to reason about.
6. **No tests in scope.** The pre-filter surfaced zero test files for `/customer`. Either tests don't exist for these endpoints or they live under a naming convention the filter missed — both warrant follow-up.
7. **No build/config in scope.** Timeouts, retries, circuit-breaker policy, and SAP credentials handling for the WebClient calling SAP are invisible. Reactive code without explicit `.timeout(...)` on downstream calls can leak subscriptions under SAP outages.

## Recommended Next Steps

**Immediate (this sprint)**
1. **Read `AdminService.getCustomer` / `searchCustomers`** to close the biggest blind spot in this review — confirm reactive purity, error mapping, EBS-vs-MSSL routing, and where `Permission` is actually enforced.
2. **Confirm authorization wiring.** Locate the gate that enforces the `/customer` permission constant in `src/main/java/io/spdigital/ubm/common/enums/Permission.java` and document it in the controller (annotation) or a SecurityConfig comment. If it's only at the service layer, add a method-security annotation on `AdminController.getCustomer` / `getCustomers` as defense-in-depth.
3. **Audit URL-borne PII.** Verify the access-log and APM pipelines scrub `bpNo` and `userId` from `GET /admin/customer` request URIs. If not, redact in the logging layer and consider moving identifiers off the query string for the singleton lookup.

**Short term**
4. **Resolve the Jackson namespace split** in `src/main/java/io/spdigital/ubm/service/sap/po/SAP.java`. Pick one (classic `com.fasterxml.jackson` is still the safer choice for Spring Boot today) and migrate; document the decision.
5. **Add explicit resilience to SAP calls.** Ensure the WebClient used for `/CustomerDetailsRetrieval`, `/MSSLCustomerDetailsRetrieval`, and `/CustomerProfileRetrieval` (`SAP.java:20,22,26`) has `.timeout(...)`, retry-with-backoff for idempotent reads, and a circuit breaker (Resilience4j). Verify in config files that were outside this scope.
6. **Backfill tests.** At minimum: a WebFlux slice test for `AdminController` (happy path + permission-denied + SAP-down), and a `@JsonTest` for the SAP DTOs to lock in the `SnakeUpperCaseStrategy` mapping.

**Medium term**
7. **Consider REST shape cleanup**: collapse `/admin/customer` and `/admin/customers` to `/admin/customers` (collection) + `/admin/customers/{bpNo}` (item) behind a versioned `/v2/...` prefix, with the current routes deprecated but retained for clients.
8. **Extract the EBS-vs-MSSL routing** from `AdminService` into a small strategy/router component if it isn't already, so the two SAP retrieval flows can evolve independently and be unit-tested in isolation.
9. **Document the Yggdrasil shared model boundary** — if it's a cross-service contract, breaking changes in `io.spdigital.ubm.model.dto` need a coordination process; if it's internal, the namespace name is misleading.

---

*Caveats:* This review is bounded to the 3 files matched by the `/customer` filter (`AdminController.java`, `SAP.java`, `Permission.java`). `AdminService` implementation, build/config files, and the full SAP DTO definitions were outside the pre-filtered scope; several recommendations above (resilience config, authorization wiring, test coverage) should be re-validated once those are inspected.
