# Inventory

_Agent: `researcher` (Research Specialist)_  
_Status: `success` · attempts: 1_

---

# Codebase Inventory Summary — `/customer` Feature Scope

## Language & Size
- **Language**: 100% Java (20/20 files)
- **Total size**: ~140.7 KB across 20 files
- **Project root**: `F:\02_SPG_PROJECTS\ubm-api` (Spring Boot / Spring WebFlux reactive stack — evidenced by `reactor.core.publisher.Mono`, `@RestController`, `@RequestMapping`)
- **Package root**: `io.spdigital.ubm` (UBM = likely "User/Business Management")

## Entry Point
- **`src/main/java/io/spdigital/ubm/Application.java`** — Spring Boot main application bootstrap class.

## Primary `/customer` Endpoint Surface
The feature is owned by the **Admin** module (`io.spdigital.ubm.admin`):

| Layer | File | Role |
|---|---|---|
| Controller | `admin/controller/AdminController.java` | Exposes `GET /admin/customer` (single) and `GET /admin/customers` (search) reactive endpoints |
| Service API | `admin/service/AdminService.java` | Interface declaring `getCustomer(bpNo, userId)` and `getCustomers(...)` |
| Service Impl | `admin/service/impl/AdminServiceImpl.java` | Business logic implementation |
| DTO | `admin/dto/GetCustomerResponse.java` | Response payload for `/admin/customer` |
| Test | `test/.../admin/service/impl/AdminServiceImplTest.java` | Unit tests for the service impl |

## Supporting / Cross-Cutting Files
- **Config & Security**: `config/Auth0Configuration.java`, `config/connector/ReactiveConnectorImpl.java`, `common/enums/Permission.java` — Auth0-based authN/authZ and reactive HTTP connector.
- **Logging (AOP)**: `logging/LoggableAspect.java`, `logging/RequestLoggingDecorator.java`, `logging/ResponseLoggingDecorator.java` — `@Loggable` annotation drives request/response logging around customer endpoints.
- **Downstream integration**: `service/sap/po/SAP.java` (SAP backend payloads), `model/dto/ProfileApi.java`, `model/dto/Yggdrasil` (referenced via `SearchCustomers`) — customer data is sourced from SAP and "Yggdrasil" upstream services.
- **Adjacent feature controllers** (touch customer context): `approvals/controller/ApprovalController.java`, `reports/controller/ReportController.java`, `trail/controller/TrailController.java`, `modification/service/ModificationServiceImpl.java`, `service/notifications/NotificationBannersServiceImpl.java`, `service/holidays/HolidaysServiceImpl.java`.

## Likely Entry Points for `/customer` Investigation
1. **`AdminController.getCustomer`** (line 46) — the literal `/customer` route handler.
2. **`AdminServiceImpl`** — orchestration logic, SAP/Yggdrasil integration.
3. **`GetCustomerResponse`** — response contract.
4. **`AdminServiceImplTest`** — existing test coverage to extend.

## Build / Config Files
None present in the pre-filtered scope (no `pom.xml`, `build.gradle`, `application.yml`, etc. were matched against `/customer`). Build tooling exists in the broader repo but is out of scope here.

## Notable Observations
- Reactive (WebFlux) stack — all customer endpoints return `Mono<T>`.
- Customer lookups are keyed by **`bpNo`** (Business Partner number, SAP-style) and **`userId`**.
- Authentication via **Auth0**; permissions modeled in a dedicated enum.
- Cross-cutting concerns (logging) implemented via Spring AOP `@Loggable`.
