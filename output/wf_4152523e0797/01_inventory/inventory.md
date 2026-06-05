# Inventory

_Agent: `researcher` (Research Specialist)_  
_Status: `success` · attempts: 1_

---

# Codebase Inventory Summary — `/customer` Feature Scope

## Inventory Overview
- **Total files in scope:** 50 (all under `src/main/java/io/spdigital/ubm/`)
- **Total size:** ~125.7 KB (~123 KB of Java source)
- **Language distribution:** 100% Java (50/50 files)
- **Root package:** `io.spdigital.ubm` (project: `ubm-api`)
- **Stack signals:** Spring Boot (Web MVC + WebFlux/Reactor), Lombok, Auth0, Sentry — based on imports (`RestController`, `Mono`, `Auth0Configuration`, `SentryConfig`, `WebClientConfiguration`).

## Module / Package Breakdown (within scope)
| Package | Files | Role |
|---|---|---|
| `admin/controller` | 1 | HTTP entry point — **`AdminController`** exposes `/admin/customers` |
| `admin/service` (+ `impl`) | 4 | `AdminService`, `UserService` and implementations — customer business logic |
| `admin/dto` | 5 | Request/response payloads: `GetCustomerResponse`, `Subscription`, `UpdateBpNo`, `ForgotPassword` |
| `approvals/controller` | 1 | `ApprovalController` — secondary surface touching customer flows |
| `service/sap` (+ `po`) | 2 | `SAPServiceImpl`, `SAP` — SAP backend integration for customer/BP data |
| `service/audit` | 5 | Audit logging of customer actions (`AuditType`, `AuditConstants`, `Audit` DTO) |
| `service/notifications` | 3 | Customer-facing banner/notification service |
| `service/holidays` | 2 | Holiday lookup (likely tied to customer SLA contexts) |
| `common` | 5 | `SecurityContextHeader`, permission enums (`Permission`, `SkipURLPermission`, `YesOrNo`, `OnOrNo`, `Utility`) |
| `config` | 9 | Spring config: security, CORS, Auth0, WebClient, proxy, Sentry, connection, permissions |
| `logging` | 5 | `@Loggable` aspect, request/response decorators, masking |
| `web` | 1 | `RequestLoggingFilter` |
| `util` | 3 | `FileUtil`, `MaskingUtil`, `AccountUtility` |
| `exception` | 2 | `UbmApiException`, `NotFoundException` |
| `service` (root) | 1 | `TestServiceImpl` |

## Likely Entry Points (HTTP-facing)
1. **`admin/controller/AdminController.java`** — primary customer endpoint
   - `GET /admin/customers` → `adminService.getCustomers(...)` returning `Mono<SearchCustomers.Response>`
   - Uses paging params (`pageNumber`, `pageSize`, `direction`) with defaults from `common.Constants`
   - Matches at lines 36, 46 — second match likely a second customer-related route (truncated)
2. **`approvals/controller/ApprovalController.java`** — secondary entry exposing customer-touching approval flows.
3. **`admin/service/impl/AdminServiceImpl.java`** — orchestrates customer lookup; delegates to SAP layer.
4. **`service/sap/SAPServiceImpl.java`** — outbound integration; likely the actual data source for `/customers`.

## Configuration / Build Surface
- **Spring config classes (9):** `SecurityConfiguration`, `Auth0Configuration`, `CorsConfig` + `CorsProperties`, `WebClientConfiguration`, `SecurityProperties`, `ProxyProperties`, `ConnectionProperties`, `SentryConfig`, `PermissionFilter`.
- **Cross-cutting filters/aspects:** `PermissionFilter` (URL-permission enforcement using `Permission` / `SkipURLPermission` enums), `RequestLoggingFilter`, `LoggableAspect` (`@Loggable` annotation seen on the customer endpoint), `LogMasking` / `MaskingUtil` for PII redaction.
- **No build manifest in scope** — `pom.xml` / `build.gradle` were not part of the feature-scoped file set, but the package layout (`src/main/java/...`) and Spring annotations strongly indicate a Maven/Gradle Spring Boot service.

## Notable Top-Level Observations
- The `/customer` feature is implemented as a **read-oriented admin surface** (`GET /admin/customers`) backed by SAP, with cross-cutting **auth (Auth0 + permission filter)**, **audit trail**, **structured/masked logging**, and **reactive client (WebClient/Mono)** plumbing.
- DTOs `GetCustomerResponse`, `Subscription`, `UpdateBpNo` suggest the feature also covers **customer subscription** detail and **BP (Business Partner) number updates** — likely additional endpoints beyond the truncated controller view.
- No test files appear in the scoped set — either tests are absent for this feature or excluded by the feature filter.
