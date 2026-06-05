# Inventory

_Agent: `researcher` (Research Specialist)_  
_Status: `success` · attempts: 1_

---

# Codebase Inventory — `/customer` Feature Scope

## Inventory Overview

| Metric | Value |
|---|---|
| Repository root | `F:\02_SPG_PROJECTS\ubm-api` |
| Files in scope | 3 |
| Total size | 22,286 bytes (~22 KB) |
| Dominant language | **Java (100%)** — 3 of 3 files |
| Feature query | `/customer` |

## Files in Scope

| Path | Size | Role |
|---|---|---|
| `src/main/java/io/spdigital/ubm/admin/controller/AdminController.java` | 3,837 B | REST entry point (Spring `@RestController`) |
| `src/main/java/io/spdigital/ubm/service/sap/po/SAP.java` | 15,185 B | SAP integration constants/DTOs (interface holding payload objects) |
| `src/main/java/io/spdigital/ubm/common/enums/Permission.java` | ~3,264 B | Permission enum (auth/authorization metadata) |

## Likely Entry Points

- **HTTP entry point for `/customer`**: `AdminController.getCustomer(...)` at `AdminController.java:46` — `GET /admin/customer?bpNo=...&userId=...`, returns `Mono<GetCustomerResponse>`. Delegates to `AdminService.getCustomer(bpNo, userId)`.
- **Related list endpoint**: `AdminController.getCustomers(...)` at line 36 — `GET /admin/customers` (search by type/searchString with pagination).
- **Downstream integration path**: `SAP.java` defines SAP service endpoint constants — `EBS_CUSTOMER_DETAILS_RETRIEVAL = "/CustomerDetailsRetrieval"` (line 20) and `CUSTOMER_PROFILE_RETRIEVAL = "/CustomerProfileRetrieval"` (line 26), indicating customer reads are backed by SAP calls.

## Stack & Framework Signals

- **Spring Boot WebFlux** (reactive): `Mono<>` return types, `@RestController`, `@RequestMapping`, `@GetMapping`.
- **Lombok** annotations (`@RequiredArgsConstructor`, `@Slf4j`, `@Builder`, `@Data`, `@Value`) → standard Lombok-driven boilerplate reduction.
- **Jackson** for JSON (`@JsonProperty`, `@JsonNaming` with `SnakeUpperCaseStrategy`) — SAP payloads use SNAKE_UPPER_CASE.
- **Custom cross-cutting**: `@Loggable` annotation (custom logging aspect from `io.spdigital.ubm.logging`).
- **Package root**: `io.spdigital.ubm` (Singapore Power Digital — Utility Bill Management API).

## Config / Build Files

None of the 3 in-scope files are config/build artifacts — all are production Java sources. The scan did not include `pom.xml` / `build.gradle` / `application.yml`; build tooling cannot be confirmed from this slice alone, though the Spring/Lombok/Jackson signature is consistent with a Maven or Gradle Spring Boot project.

## Notable Observations

- The `/customer` feature is exposed under the `/admin` base path (full route: `GET /admin/customer`), suggesting it is an administrative lookup, not a customer-facing endpoint.
- The controller is thin — business logic lives in `AdminService` (not in the scoped files), and data is sourced from SAP via the constants in `SAP.java`.
- `Permission.java` appearing in scope implies `/customer` access is gated by a permission enum value (likely a `CUSTOMER_*` or `ADMIN_*` constant; full content was truncated in the input).
