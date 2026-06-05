# Inventory

_Agent: `researcher` (Research Specialist)_  
_Status: `success` · attempts: 1_

---

# Codebase Inventory Summary — Feature `/customer`

## Scope Overview
- **Project root**: `F:\02_SPG_PROJECTS\ubm-api`
- **Feature query**: `/customer`
- **Files matched**: 3
- **Total size**: 22,286 bytes (~22 KB)
- **Language distribution**: 100% Java (3/3 files)

## Files in Scope

| # | Path | Size | Match Lines | Role |
|---|------|------|-------------|------|
| 1 | `src/main/java/io/spdigital/ubm/admin/controller/AdminController.java` | 3,837 B | 36, 46 | HTTP entry point |
| 2 | `src/main/java/io/spdigital/ubm/service/sap/po/SAP.java` | 15,185 B | 20, 26 | SAP integration DTOs / constants |
| 3 | `src/main/java/io/spdigital/ubm/common/enums/Permission.java` | (remainder) | — | Permission enum (authorization) |

## Dominant Language & Framework Signals
- **Language**: Java (exclusively)
- **Framework stack** (inferred from imports in `AdminController.java`):
  - **Spring WebFlux** — reactive `Mono<T>` return types, `@RestController`, `@RequestMapping`, `@GetMapping`, `@PostMapping`, `@DeleteMapping`
  - **Project Reactor** — `reactor.core.publisher.Mono`
  - **Lombok** — `@RequiredArgsConstructor`, `@Slf4j`, `@Data`, `@Builder`, `@Value`, `@SuperBuilder`
  - **Jackson** — `@JsonProperty`, `@JsonNaming` with a custom `SnakeUpperCaseStrategy` (SAP wire format)
  - **SLF4J** logging via Lombok `@Slf4j`
- **Package root**: `io.spdigital.ubm` (SP Digital — UBM = User/Billing Management domain)

## Likely Entry Points for `/customer`
The HTTP-facing entry point is **`AdminController`** under base path `/admin`:

1. **`GET /admin/customers`** (line 36) — `getCustomers(type, searchString, pageNumber, pageSize, direction)` → returns `Mono<Yggdrasil.SearchCustomers.Response>`; delegates to `AdminService.getCustomers(...)`.
2. **`GET /admin/customer`** (line 46) — `getCustomer(bpNo, userId)` → returns `Mono<GetCustomerResponse>`; delegates to `AdminService.getCustomer(bpNo, userId)`.

Both methods are annotated with `@Loggable` (custom AOP-style logging aspect under `io.spdigital.ubm.logging`).

## Downstream / Integration Layer
- **`SAP.java`** is an `interface` acting as a constants + DTO container for SAP backend calls. Notable customer-related endpoint constants:
  - `EBS_CUSTOMER_DETAILS_RETRIEVAL = "/CustomerDetailsRetrieval"` (line 20)
  - `MSSL_CUSTOMER_DETAILS_RETRIEVAL = "/MSSLCustomerDetailsRetrieval"` (line 22)
  - `CUSTOMER_PROFILE_RETRIEVAL = "/CustomerProfileRetrieval"` (line 26)
- Uses **SnakeUpperCaseStrategy** for JSON naming → SAP expects SCREAMING_SNAKE_CASE keys.
- Pulls in `MaskingUtil` → PII masking on SAP responses is part of the customer-data flow.

## Authorization
- **`Permission.java`** (enum) is the third in-scope file — implies `/customer` endpoints are gated by a permission constant defined here (e.g., role/permission checks via Spring Security or a custom annotation).

## Config / Build Files
**None present in this feature-scoped slice.** The pre-filter excludes top-level build descriptors. Based on package layout (`src/main/java/...`) and Spring/Lombok usage, the project is almost certainly built with **Maven (`pom.xml`)** or **Gradle (`build.gradle[.kts]`)** at the repo root — out of scope here.

## Notable Constants & Conventions
- Pagination/sorting defaults imported from `io.spdigital.ubm.common.Constants`: `DEFAULT_PAGE_NUMBER`, `DEFAULT_PAGE_SIZE`, `DEFAULT_SORT_DIRECTION`.
- `Yggdrasil` appears to be a shared DTO namespace (likely user-identity domain inside `io.spdigital.ubm.model.dto`).
- DTO conventions: separate `*.Request` / `*.Response` nested classes (e.g., `Subscription.Update.Request`, `SearchCustomers.Response`).

## Architecture Snapshot
```
HTTP (Spring WebFlux)
   └── AdminController  ── @Loggable ──> AdminService (reactive Mono)
                                          └── SAP integration (SAP.java DTOs/paths)
                                                  ├── /CustomerDetailsRetrieval
                                                  ├── /MSSLCustomerDetailsRetrieval
                                                  └── /CustomerProfileRetrieval
   └── Permission enum  ── authorization gate
```

## Gaps / Not Visible in Scope
- `AdminService` and `GetCustomerResponse` implementations are referenced but not in the matched files — likely contain the orchestration logic between controller and SAP layer.
- The truncated portion of `SAP.java` (≈20 KB of additional content) likely contains the request/response DTO classes for the three customer endpoints.
- No test files, no build descriptor, no application configuration (`application.yml`/`application.properties`) appear in this scope.
