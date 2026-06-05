# Report

_Agent: `assistant` (General Assistant)_  
_Status: `success` · attempts: 1_

---

# Final Analysis Report — `/customer` Feature (UBM API)

**Prepared for:** Engineering Lead
**Scope:** `/customer` endpoints owned by `io.spdigital.ubm.admin` module
**Date:** 2026-06-04

---

## Overview

The `/customer` feature is not a standalone module but a pair of read-only HTTP endpoints exposed by the `admin` module of `ubm-api`, a Spring Boot / WebFlux reactive Java service rooted at `io.spdigital.ubm`:

| HTTP | Path | Handler | Return Type |
|---|---|---|---|
| `GET` | `/admin/customer` | `AdminController.getCustomer(bpNo, userId)` | `Mono<GetCustomerResponse>` |
| `GET` | `/admin/customers` | `AdminController.getCustomers(...)` | `Mono<Yggdrasil.SearchCustomers.Response>` |

Both routes act as an authenticated aggregation layer between Auth0-protected admin clients and two upstream systems of record:

- **SAP** — business-partner / customer master data, keyed by `bpNo` (`service/sap/po/SAP.java`).
- **Yggdrasil** — internal identity/user search service (`model/dto/Yggdrasil` referenced via `SearchCustomers`).

The reactive orchestration lives in `admin/service/impl/AdminServiceImpl.java`, with the public contract declared in `admin/service/AdminService.java` and the wire contract in `admin/dto/GetCustomerResponse.java`. The only test in scope is `AdminServiceImplTest.java`.

Total feature surface in the pre-filtered inventory: **20 Java files, ~140.7 KB**, of which 5 are directly part of the `/customer` slice; the remainder are cross-cutting (Auth0 config, reactive connector, AOP logging, permissions enum) or adjacent features (`approvals`, `reports`, `trail`, `modification`, notifications, holidays) that share the same admin/customer context.

---

## Architecture

**Layering (within `io.spdigital.ubm.admin`)** follows a clean, conventional 3-layer split:

```
admin/
 ├── controller/AdminController       ← HTTP boundary, @RestController, reactive returns
 ├── service/AdminService             ← application interface
 ├── service/impl/AdminServiceImpl    ← orchestration / business logic
 └── dto/GetCustomerResponse          ← outbound wire contract
```

Constructor injection via Lombok `@RequiredArgsConstructor` is used throughout; no field injection observed in `AdminController`. This keeps the controller easily testable and dependency-explicit.

**Reactive stack.** Every endpoint returns `Mono<T>`. Outbound HTTP is consolidated in `config/connector/ReactiveConnectorImpl.java`, which is the single seam where `WebClient` work is composed. This implies `AdminServiceImpl` joins Yggdrasil + SAP responses non-blockingly via `Mono` combinators rather than blocking joins.

**Cross-cutting concerns.**
- **AuthN/AuthZ** — Auth0 configured in `config/Auth0Configuration.java`; authorization granularities enumerated in `common/enums/Permission.java`. Admin routes are expected to require admin-tier permissions.
- **Observability** — A `@Loggable` AOP aspect (`logging/LoggableAspect.java` + `RequestLoggingDecorator` + `ResponseLoggingDecorator`) wraps inbound requests and outbound responses around controller methods, providing uniform structured logging without polluting business logic.

**Integration shape.** `/admin/customer` is a thin read-aggregation: identifier (`bpNo`, `userId`) in, composed SAP+Yggdrasil view out. `/admin/customers` is a pure pass-through search to Yggdrasil. There is no write path, no event emission, and no caching layer visible within the `/customer` slice.

**Module coupling.** The `admin` controller co-hosts several unrelated admin operations (`/bpNos`, `/subscription`, `/users/...`) that share the same `AdminService` interface. `/customer` therefore inherits the cohesion (or lack thereof) of `AdminService` as a whole.

---

## Quality & Risk

**Strengths**
- Reactive end-to-end — no obvious blocking calls in the controller surface, so the endpoints should behave well under fan-out load to SAP/Yggdrasil.
- Clear separation of HTTP, application, and DTO layers; constructor injection makes the controller deterministic to test.
- Centralized HTTP egress (`ReactiveConnectorImpl`) and centralized auth (Auth0) keep the controller free of plumbing.
- AOP-based request/response logging gives consistent telemetry around `/customer` without instrumenting each handler.

**Risks & gaps**

1. **God-controller / God-service shape.** `AdminController` and `AdminService` host customer, bpNo, subscription, and user-management operations. As `/customer` evolves, this will keep growing the service interface and complicating its test class (`AdminServiceImplTest`). Bounded-context drift is the long-term risk.
2. **Thin test coverage.** Only one test file (`admin/service/impl/AdminServiceImplTest.java`) is in scope for the feature. No controller-level WebFlux slice tests (`@WebFluxTest`) appear in the inventory, so contract-level regressions on `GET /admin/customer` and `GET /admin/customers` are not guarded.
3. **Upstream failure semantics are not explicit.** With SAP + Yggdrasil composed reactively, partial-failure behavior (one upstream down, slow, or returning stale data) is invisible from the inventory. No resilience primitives (Resilience4j, timeouts, fallbacks) are referenced in the scanned files.
4. **Authorization not auditable from the inventory.** `Permission` enum exists, but the scan does not show a `@PreAuthorize`/permission check on `AdminController.getCustomer`. Whether `/customer` enforces an admin-only permission needs verification — high-impact since the response is customer master data.
5. **PII surface in logging.** `@Loggable` wraps request/response. Customer responses (`GetCustomerResponse`) likely contain PII; without explicit field masking, this is a compliance hazard.
6. **Wire contract leakage.** `/admin/customers` returns `Yggdrasil.SearchCustomers.Response` — an upstream DTO — rather than an admin-owned response type. Any Yggdrasil schema change becomes a breaking API change for clients.
7. **Truncated architecture input.** The architect's `codebase_scan` was truncated mid-file, so claims about `AdminServiceImpl`'s exact composition operators (`zip` vs. `flatMap` vs. sequential `then`) and error mapping are inferred. A direct read is warranted before any refactor.

---

## Recommended Next Steps

Ordered by leverage:

1. **Verify and lock authorization on `/admin/customer*`.** Confirm `AdminController.getCustomer` and `getCustomers` are guarded by an admin-tier value from `common/enums/Permission.java` (e.g., `@PreAuthorize` or a method-level filter). If absent, add it before anything else.
2. **Decouple the wire contract from Yggdrasil.** Introduce an `admin`-owned `SearchCustomersResponse` DTO and map `Yggdrasil.SearchCustomers.Response` → admin DTO inside `AdminServiceImpl`. Removes upstream-schema blast radius.
3. **Audit `@Loggable` for PII.** Either annotate sensitive fields on `GetCustomerResponse` for masking or add a logging policy in `RequestLoggingDecorator`/`ResponseLoggingDecorator` that scrubs customer identifiers and contact data.
4. **Add a WebFlux slice test** (`@WebFluxTest(AdminController.class)`) covering: 200 happy path, 401 unauthenticated, 403 unauthorized, 404 unknown `bpNo`, and 5xx upstream failure. Pair with existing `AdminServiceImplTest` for service-level coverage of SAP+Yggdrasil composition.
5. **Make upstream resilience explicit.** Add per-call timeouts and a circuit breaker (Resilience4j or equivalent) inside `ReactiveConnectorImpl` or at the `AdminServiceImpl` composition site. Define and document fallback semantics — especially whether `/admin/customer` should fail closed or return a partial view when one upstream is degraded.
6. **Plan a module split for `admin`.** Track the growth of `AdminService`. When it exceeds ~7–8 methods or its test class becomes unwieldy, extract a dedicated `customer` sub-module (`admin/customer/{controller,service,dto}`) so `/customer` becomes its own bounded slice while keeping the `/admin` URL prefix.
7. **Re-read `AdminServiceImpl.java` end-to-end** before acting on items 2 and 5 — the architect input was truncated, so confirm actual composition and error handling rather than refactor on inference.
