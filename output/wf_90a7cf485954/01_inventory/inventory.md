# Inventory

_Agent: `researcher` (Research Specialist)_  
_Status: `success` · attempts: 1_

---

# Codebase Inventory Summary — `/customer` Feature Scope

## Inventory Overview

| Metric | Value |
|---|---|
| **Feature query** | `/customer` |
| **Root path** | `F:\02_SPG_PROJECTS\ubm-api` |
| **Matched files** | 3 |
| **Total size** | 22,286 bytes (~22 KB) |
| **Languages** | Java (100%, 3/3 files) |

## Dominant Language & Framework Signals

- **Language:** Java exclusively within scope.
- **Framework stack (inferred from imports):**
  - **Spring WebFlux** — reactive endpoints returning `Mono<…>` (`@RestController`, `@GetMapping`, `@PostMapping`, `reactor.core.publisher.Mono`).
  - **Lombok** — `@RequiredArgsConstructor`, `@Slf4j`, `@Data`, `@Builder`, `@Value`, `@SuperBuilder`.
  - **Jackson** (incl. the newer `tools.jackson.databind` namespace alongside classic `com.fasterxml.jackson`) — used for SAP DTO (de)serialization with a custom `SnakeUpperCaseStrategy`.
- **Package root:** `io.spdigital.ubm` (UBM = likely a billing/customer-management service for SP Digital).

## Notable Files (the entire feature footprint)

| Path | Role | Size | Match lines |
|---|---|---:|---|
| `src/main/java/io/spdigital/ubm/admin/controller/AdminController.java` | **HTTP entry point** | 3,837 B | 36, 46 |
| `src/main/java/io/spdigital/ubm/service/sap/po/SAP.java` | SAP integration constants + DTO interface | 15,185 B | 20, 26 |
| `src/main/java/io/spdigital/ubm/common/enums/Permission.java` | Permission enum (content truncated in input) | (remainder) | — |

## Likely Entry Points

- **Primary REST entry point for `/customer`:**
  `AdminController` (mapped under `@RequestMapping("/admin")`).
  - `GET /admin/customer` → `getCustomer(bpNo, userId)` → delegates to `AdminService.getCustomer(...)` returning `Mono<GetCustomerResponse>` (line 46).
  - Adjacent endpoint: `GET /admin/customers` → `getCustomers(type, searchString, pageNumber, pageSize, direction)` returning `Mono<SearchCustomers.Response>` (line 36).
- **Downstream integration entry point:** `SAP` interface declares the SAP backend endpoint constants the service calls into:
  - `EBS_CUSTOMER_DETAILS_RETRIEVAL = "/CustomerDetailsRetrieval"` (line 20)
  - `MSSL_CUSTOMER_DETAILS_RETRIEVAL = "/MSSLCustomerDetailsRetrieval"` (line 22)
  - `CUSTOMER_PROFILE_RETRIEVAL = "/CustomerProfileRetrieval"` (line 26)
  - `UPDATE_BILL_PREFERENCE = "/UpdateBillPreference"` (line 24)

## Config / Build Files

**None present in scope.** No `pom.xml`, `build.gradle`, `application.yml`, `Dockerfile`, or CI config was matched by the `/customer` filter. Build/config files exist in the broader repo but fall outside the pre-filtered feature scope and are not described here per instructions.

## Architectural Notes Specific to `/customer`

- **Layering:** Controller (`admin.controller`) → Service (`admin.service.AdminService`) → SAP integration (`service.sap.po.SAP`). Classic 3-layer reactive Spring split.
- **DTOs in play:** `GetCustomerResponse`, `Yggdrasil.SearchCustomers`, `Subscription`, `UpdateBpNo` (all under `io.spdigital.ubm.admin.dto` / `io.spdigital.ubm.model.dto`). "Yggdrasil" appears to be the name of a shared model namespace.
- **Cross-cutting concerns:** `@Loggable` annotation on every endpoint (custom AOP from `io.spdigital.ubm.logging`); shared constants from `io.spdigital.ubm.common.Constants` (pagination defaults); masking helper `MaskingUtil` referenced by SAP DTOs.
- **Authorization:** `Permission` enum (in scope but content truncated) likely defines the permission constant gating customer-detail access.

## Caveats

- `SAP.java` content was truncated (~20 KB more not shown); full DTO shapes for SAP customer-retrieval payloads were not analyzed.
- `Permission.java` content was not included in the visible portion of the input — only its path is confirmed in scope.
- Scope is narrow (3 files); the actual service implementation (`AdminService.getCustomer`) is **not** in the pre-filtered set, so the business logic behind `/admin/customer` is out of view.
