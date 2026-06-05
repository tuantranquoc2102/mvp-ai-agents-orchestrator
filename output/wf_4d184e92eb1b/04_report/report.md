# Report

_Agent: `assistant` (General Assistant)_  
_Status: `success` · attempts: 1_

---

# Final Analysis Report — Feature `/customer`

**Prepared for:** Engineering Lead
**Scope:** `/customer` feature slice in `ubm-api` (3 files: `AdminController.java`, `service/sap/po/SAP.java`, `common/enums/Permission.java`)

---

## Overview

The `/customer` feature exposes a thin **reactive REST facade** over the downstream SAP back-office for an electricity/utility billing platform (UBM). Two endpoints are surfaced from `AdminController` under the `/admin` base path:

| Method | Path | Handler | Purpose |
|---|---|---|---|
| GET | `/admin/customer` | `AdminController#getCustomer(bpNo, userId)` | Retrieve a single customer by Business Partner number |
| GET | `/admin/customers` | `AdminController#getCustomers(type, searchString, pageNumber, pageSize, direction)` | Paginated customer search |

The implementation is a single-language Java stack (~22 KB across 3 files in scope) using **Spring WebFlux** (`Mono<…>`), **Lombok**, **Jackson** with a custom `SnakeUpperCaseStrategy` for SAP payload marshalling, and an `@Loggable` AOP aspect for cross-cutting instrumentation. Business orchestration lives in `AdminService` (out of scope filter), and downstream SAP integration is contracted via the `SAP` interface in `service/sap/po/SAP.java`, which enumerates the relevant endpoint paths (`/CustomerDetailsRetrieval`, `/MSSLCustomerDetailsRetrieval`, `/CustomerProfileRetrieval`).

`Permission.java` is referenced as the RBAC vocabulary, but the authorization wiring itself is not visible in this slice.

---

## Architecture

**Layering** follows a conventional controller → service → integration topology:

```
io.spdigital.ubm
├── admin.controller     ← AdminController (web layer, @RestController("/admin"))
├── admin.service        ← AdminService (orchestration; not in slice)
├── admin.dto            ← GetCustomerResponse, Subscription, UpdateBpNo
├── service.sap.po       ← SAP integration contract (endpoint path constants + payload objects)
├── model.dto            ← BaseResponse, Yggdrasil.SearchCustomers envelopes
├── common.enums         ← Permission (RBAC vocabulary)
├── logging              ← @Loggable AOP aspect
└── util                 ← MaskingUtil, SnakeUpperCaseStrategy
```

**Style & patterns:**
- **Reactive end-to-end** via Project Reactor `Mono<…>` — non-blocking, suitable for fan-out to slow SAP calls.
- **Thin controllers**: `AdminController.getCustomer` (line 46) is a pass-through to `AdminService`, with `@Loggable` providing observability without polluting handler bodies.
- **DTO segregation**: distinct admin-facing DTOs (`GetCustomerResponse`, `Subscription`, `UpdateBpNo`) versus SAP wire-format payload objects with `SnakeUpperCaseStrategy` (Jackson) — a clear, well-scoped inbound/outbound boundary.
- **Constants externalized**: pagination defaults (`DEFAULT_PAGE_NUMBER`, `DEFAULT_PAGE_SIZE`, `DEFAULT_SORT_DIRECTION`) come from `common.Constants`.

**Communication:**
- **Inbound**: REST/JSON over HTTP (WebFlux).
- **Outbound**: SAP back-office via paths declared in `SAP.java` — EBS variant (`/CustomerDetailsRetrieval`, line 20), MSSL variant (`/MSSLCustomerDetailsRetrieval`, line 26), plus `/CustomerProfileRetrieval`. The EBS/MSSL split implies a routing decision (likely by customer type) inside `AdminService`.

---

## Quality & Risk

**Strengths**
- Clean separation between web, service, and integration layers; controllers are appropriately thin.
- Reactive types throughout — good fit for I/O-bound SAP fan-out, no thread-blocking liabilities visible at the controller boundary.
- DTO boundary is explicit; SAP wire format is isolated from the admin-facing response shape, with `MaskingUtil` available for sensitive-field handling.
- AOP-based logging (`@Loggable`) keeps handler code uncluttered while still producing structured request traces.

**Risks & Concerns**

1. **Mixed Jackson namespaces in `SAP.java`** (flagged in inventory): the file imports `tools.jackson.databind.annotation.JsonNaming` (Jackson 3) alongside `com.fasterxml.jackson.annotation.JsonProperty` (Jackson 2). This is a real correctness/build-stability hazard — Jackson 3 is API-incompatible with Jackson 2, and mixing the two in one compilation unit usually indicates either an unintentional auto-import or an in-flight migration. **High-priority cleanup.**
2. **Authorization wiring not visible**: `Permission.java` defines the vocabulary, but nothing in the slice demonstrates that `/admin/customer` and `/admin/customers` are actually gated. Given these are admin endpoints returning PII-equivalent billing data, the absence of visible `@PreAuthorize` / `SecurityContextHeader` enforcement at the controller is a gap that needs verification.
3. **Configuration not in slice**: no `application.yml`, no `@Configuration` classes, no `pom.xml`/`build.gradle`. SAP base URL, timeout, retry, and circuit-breaker policies cannot be assessed from these files. For a downstream that is historically slow and occasionally flaky (SAP), resilience configuration is a typical blind spot.
4. **No tests in scope**: the feature filter returned zero test files. Either tests live under a different naming convention not matched by the `/customer` filter, or the feature is under-tested. The latter is a meaningful risk given the EBS-vs-MSSL routing branch and PII masking logic.
5. **Pagination contract**: `getCustomers` accepts `type`, `searchString`, `pageNumber`, `pageSize`, `direction` but no `sortBy` field visible in the inventory excerpt — worth confirming the sort key is fixed, and that `pageSize` has an upper bound to prevent expensive SAP scans.
6. **PII / masking**: `MaskingUtil` exists, but whether it's applied to `GetCustomerResponse` before serialization is not demonstrable from the slice. Customer details from SAP typically include NRIC/passport equivalents — needs audit.

---

## Recommended Next Steps

In rough priority order:

1. **Resolve the Jackson 2/3 mix in `src/main/java/io/spdigital/ubm/service/sap/po/SAP.java`.** Pick one major version, align all imports, and add a static-analysis or ArchUnit rule banning the other namespace to prevent regression. Re-run a full build and the SAP-integration test suite afterwards.
2. **Audit authorization on the two `/customer` endpoints.** Confirm `AdminController#getCustomer` and `#getCustomers` are gated by a `Permission` check (likely via `@PreAuthorize` or a WebFlux `SecurityWebFilterChain`). If gating is implicit (e.g. global filter on `/admin/**`), document it in the controller Javadoc so the contract is explicit at the call site.
3. **Verify PII masking is applied on the response path** — specifically that `GetCustomerResponse` runs through `MaskingUtil` (or equivalent Jackson serializer) before leaving the service. Add a serialization-layer test asserting that sensitive fields are masked.
4. **Locate or add tests for the `/customer` slice.** Look beyond the current filter for `AdminControllerTest`, `AdminServiceTest`, and any WireMock-based SAP contract tests. If absent, prioritize: (a) controller slice test for both endpoints, (b) service-layer test covering the EBS-vs-MSSL routing decision, (c) Jackson round-trip test for SAP payload objects.
5. **Review SAP client resilience configuration** (outside the slice but adjacent): timeouts, retries, and circuit breakers on `WebClient` calls to `/CustomerDetailsRetrieval` and `/MSSLCustomerDetailsRetrieval`. Slow SAP responses will tie up reactor threads' downstream consumers if backpressure is not respected.
6. **Constrain `getCustomers` pagination**: add a maximum `pageSize` (and validate `direction` against an allow-list) at the controller to prevent unbounded SAP scans triggered by client input.
7. **Document the EBS-vs-MSSL routing rule** in `AdminService` Javadoc or a short ADR. The two retrieval paths in `SAP.java` (lines 20, 26) imply a branching policy that a new engineer will not infer from reading the controller alone.
