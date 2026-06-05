# Inventory

_Agent: `researcher` (Research Specialist)_  
_Status: `success` · attempts: 1_

---

# Codebase Inventory — Feature `/customer`

## Inventory Snapshot
- **Scope path**: `F:\02_SPG_PROJECTS\ubm-api`
- **Files matching feature**: 3
- **Total size**: 22,286 bytes (~22 KB)
- **Languages**: Java (100%) — 3/3 files
- **Build/runtime profile**: Spring Boot reactive (Project Reactor `Mono`, `@RestController`), Lombok, Jackson — typical Maven/Gradle Java service layout under `src/main/java`.

## Dominant Language & Style
- **Java** exclusively, package root `io.spdigital.ubm.*`.
- Reactive WebFlux style (`Mono<…>`), DTO-driven, annotation-based REST mapping.
- Uses Lombok (`@RequiredArgsConstructor`, `@Slf4j`, `@Data`, `@Builder`, `@Value`, `@SuperBuilder`) and Jackson with `SnakeUpperCaseStrategy` for SAP payloads.

## Notable Files in `/customer` Scope

| File | Size | Role |
|---|---|---|
| `src/main/java/io/spdigital/ubm/admin/controller/AdminController.java` | 3,837 B | HTTP entry point — exposes `/customer` endpoints |
| `src/main/java/io/spdigital/ubm/service/sap/po/SAP.java` | 15,185 B | Downstream SAP integration contract (interface + DTOs) |
| `src/main/java/io/spdigital/ubm/common/enums/Permission.java` | (remainder ~3.3 KB) | Permission enum referencing customer-related authz |

## Likely Entry Points (feature-scoped)
- **REST entry**: `AdminController` at base path `/admin`
  - `GET /admin/customer` → `getCustomer(bpNo, userId)` → `adminService.getCustomer(...)` (line 46) — the primary `/customer` endpoint.
  - `GET /admin/customers` → `getCustomers(type, searchString, pageNumber, pageSize, direction)` (line 36) — companion search endpoint returning `Yggdrasil.SearchCustomers.Response`.
- **Service boundary**: `AdminService` (injected; not in scope filter) handles orchestration; controller is a thin pass-through with `@Loggable` instrumentation.
- **Downstream integration**: `SAP` interface declares SAP endpoint path constants used to retrieve customer data:
  - `EBS_CUSTOMER_DETAILS_RETRIEVAL = "/CustomerDetailsRetrieval"` (line 20)
  - `MSSL_CUSTOMER_DETAILS_RETRIEVAL = "/MSSLCustomerDetailsRetrieval"` (line 26)
  - Also `CUSTOMER_PROFILE_RETRIEVAL = "/CustomerProfileRetrieval"`.

## Config / Build Files
- None present in the feature-filtered set. `codebase_scan` was pre-filtered to `/customer` references, so top-level build files (`pom.xml` / `build.gradle`), `application.yml`, and Spring `@Configuration` classes were excluded from this slice. Their existence is inferred from Spring Boot conventions (`src/main/java` layout, `@RestController`, reactive types) but cannot be confirmed from the provided inputs.

## Key Observations
- The `/customer` feature surface is a **thin reactive REST facade over SAP**: `AdminController.getCustomer` delegates to `AdminService`, which is expected to call SAP via paths declared in `SAP.java` (`/CustomerDetailsRetrieval`, `/MSSLCustomerDetailsRetrieval`, `/CustomerProfileRetrieval`).
- DTOs split between admin-facing (`GetCustomerResponse`, `Subscription`, `UpdateBpNo`) and SAP wire-format (snake-upper-case naming, masking utilities) — clear inbound/outbound boundary.
- `Permission.java` (truncated in input) suggests RBAC gating on customer operations, though the authz wiring itself is not in this slice.
- Note: `SAP.java` imports `tools.jackson.databind.annotation.JsonNaming` (Jackson 3 namespace) alongside `com.fasterxml.jackson.annotation.JsonProperty` (Jackson 2) — a mixed-Jackson import worth flagging to downstream reviewers.
