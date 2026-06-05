# Architecture

_Agent: `architect` (Software Architect)_  
_Status: `success` · attempts: 1_

---

# Architecture Analysis — `/customer` Feature

## Scope of this Analysis
The pre-filtered scan returned **3 Java files** in the Spring Boot project `ubm-api`. Only `AdminController.java` was returned in full; `SAP.java` was truncated mid-content and `Permission.java` content was not included in the scan payload. Conclusions below are limited to what those files reveal.

---

## 1. Layering & Module Topology

The feature follows a **classic layered Spring (WebFlux) architecture** with package-by-feature on top:

```
io.spdigital.ubm
├── admin                          ← feature module (presentation + app services)
│   ├── controller.AdminController  (REST entry point)
│   ├── service.AdminService        (orchestration — interface inferred)
│   ├── service.UserService         (auxiliary — forgot-password)
│   └── dto                         (GetCustomerResponse, Subscription, UpdateBpNo)
├── service.sap.po.SAP             ← downstream integration contract (SAP backend)
├── model.dto                       (cross-cutting Yggdrasil, BaseResponse)
├── common                          (Constants, SecurityContextHeader, UserUtil)
├── common.enums.Permission         (authorization tokens — likely RBAC enum)
└── logging.Loggable                (cross-cutting @Loggable aspect/annotation)
```

**Stack indicators**

| Concern        | Evidence                                                                     |
| -------------- | ---------------------------------------------------------------------------- |
| Web framework  | `@RestController`, `org.springframework.web.bind.annotation.*`               |
| Reactive style | All handlers return `Mono<…>` → **Spring WebFlux / Project Reactor**         |
| Boilerplate    | Lombok (`@RequiredArgsConstructor`, `@Slf4j`, `@Data`, `@Builder`, `@Value`) |
| Serialization  | Jackson + custom `SnakeUpperCaseStrategy` + `MaskingUtil` (PII masking)      |
| Java version   | Mixed-package imports (`tools.jackson.databind` alongside `com.fasterxml`) — see smell #3 |

---

## 2. The `/customer` Slice (Request Flow)

```
HTTP GET /admin/customer?bpNo=…&userId=…
        │
        ▼
AdminController.getCustomer(bpNo, userId)            [presentation]
        │   @Loggable cross-cut (audit / structured log)
        ▼
AdminService.getCustomer(bpNo, userId) : Mono<GetCustomerResponse>   [application service — interface]
        │
        ▼ (inferred)
SAP integration layer  ──►  external SAP endpoints declared in SAP.java:
        │                       /CustomerDetailsRetrieval        (EBS)
        │                       /MSSLCustomerDetailsRetrieval    (MSSL utility)
        │                       /CustomerProfileRetrieval
        │                       /UpdateBillPreference
        ▼
GetCustomerResponse  (admin.dto)  ◄── mapped via SnakeUpperCaseStrategy
        │                                + MaskingUtil applied to PII
        ▼
JSON to caller
```

Companion endpoint `GET /admin/customers` (collection search) delegates to `adminService.getCustomers(type, searchString, page, size, direction)` and returns the shared `Yggdrasil.SearchCustomers.Response` envelope — suggesting **Yggdrasil is an internal aggregation/identity service** used in parallel to SAP.

---

## 3. External Dependencies & Communication

| Direction | Counterpart       | Channel                                                                                    | Purpose                                                |
| --------- | ----------------- | ------------------------------------------------------------------------------------------ | ------------------------------------------------------ |
| Outbound  | **SAP**           | HTTP (paths in `SAP.java`: `EBS_CUSTOMER_DETAILS_RETRIEVAL`, `MSSL_…`, `CUSTOMER_PROFILE_RETRIEVAL`, `UPDATE_BILL_PREFERENCE`) | Source of truth for customer master / billing profile  |
| Outbound  | **Yggdrasil**     | DTO envelope reused (`model.dto.Yggdrasil.*`)                                              | Identity / user-to-BP linkage, search, delink          |
| Inbound   | Admin UI / BFF    | REST under `/admin/*`                                                                      | Customer service-rep operations                        |
| Cross-cut | `SecurityContextHeader`, `UserUtil`, `Permission` enum | In-process                                                          | AuthN/AuthZ propagation                                |

Communication is **synchronous request/response over HTTP**, made non-blocking by Reactor (`Mono`). There is no evidence of messaging, event-sourcing, or scheduled jobs in this slice.

---

## 4. Structural Observations

### ✅ What's good
- **Reactive end-to-end** in the slice — no `block()` calls in the controller.
- **DTOs are feature-local** (`admin.dto.GetCustomerResponse`, `UpdateBpNo`, `Subscription`) — the feature owns its presentation contract.
- **Cross-cutting concerns externalised** via `@Loggable` and Lombok — controller stays thin (delegates only).
- **PII protection** is centralised in `MaskingUtil`, applied at the SAP payload layer rather than ad-hoc per field.

### ⚠️ Smells & risks

1. **`AdminController` is becoming a god controller.**
   It already exposes **10 endpoints across 4 unrelated capability domains**: customer lookup (`/customer`, `/customers`), BP-No CRUD (`/bpNos/*`), subscriptions (`/subscription`, `/retrieve/subscription`), user account ops (`/users/delink`, `/users/forgot-password`). The single-controller pattern will keep growing and violates SRP. Recommend splitting into `CustomerController`, `BpNoController`, `SubscriptionController`, `UserAccountController`.

2. **Inconsistent endpoint naming.**
   - `GET /admin/customer?bpNo=…` uses a singular collection name with query-param ID — non-REST-idiomatic. A proper resource form is `GET /admin/customers/{bpNo}` (already used elsewhere — `/bpNos/accountNo/{accountNo}`).
   - `POST /admin/retrieve/subscription` is RPC-style verbing under a REST controller; mixes paradigms.

3. **Mixed Jackson packages.**
   `SAP.java` imports both `com.fasterxml.jackson.annotation.JsonProperty` **and** `tools.jackson.databind.annotation.JsonNaming`. `tools.jackson.*` is the **Jackson 3.x** namespace; `com.fasterxml.jackson.*` is **2.x**. Having both on the classpath risks annotation-processing inconsistencies (one annotation seen by one ObjectMapper, ignored by another). Pick one major version.

4. **Error handling is per-endpoint and inconsistent.**
   `getBpNoByAccountNo` swallows any error and returns 204 No Content (`onErrorResume → noContent`). The `/customer` endpoint has **no** `onErrorResume` — failures propagate as 500s unless a global `@ControllerAdvice` exists (not in scope). The behaviour for "customer not found" is therefore ambiguous between endpoints.

5. **`SAP` interface used as a constants holder.**
   Java `interface` for grouping `public static final String` constants is the classic *Constant Interface antipasso*. It pollutes any implementing class with these constants. Prefer a `final class SAP { private SAP() {} … }` or `enum`. (Truncated content suggested it also defines DTOs via `@Value`/`@SuperBuilder`, which is fine — but mixing constants + nested DTOs in one type bloats it.)

6. **DTO leakage across modules.**
   `AdminController` imports `io.spdigital.ubm.model.dto.Yggdrasil` — a model from another package — and uses its nested types (`Yggdrasil.SearchCustomers.Response`, `Yggdrasil.User.Request`) directly as the controller's wire contract. This **couples the public REST API to the internal Yggdrasil service contract**: any change to that downstream DTO breaks consumers of `/admin/customers`. Introduce an admin-owned response DTO and map.

7. **Pagination defaults via String constants.**
   `DEFAULT_PAGE_NUMBER` / `DEFAULT_PAGE_SIZE` / `DEFAULT_SORT_DIRECTION` are strings injected via `defaultValue = …`. Type-safe `Pageable` (or a Reactor-equivalent paging argument resolver) would be cleaner and remove parse-error risk.

8. **No visible authorization on `/customer`.**
   `Permission` enum exists in the codebase and is presumably wired via method-security annotations elsewhere — but **none of the handlers in this controller carry `@PreAuthorize` or equivalent**. For an admin-facing customer-data endpoint that returns PII, authorization must be explicit and verifiable in code, not implicit at the gateway.

### No cycle evidence in scope
Only forward dependencies are visible: `admin → admin.service → (service.sap, model.dto)`, `admin → common`. With three files I cannot rule out cycles elsewhere, but the slice itself is acyclic.

---

## 5. Summary

The `/customer` feature is a **thin reactive REST handler over a SAP-backed customer-master lookup**, wrapped by a shared admin controller that also handles BP-No, subscription, and user account flows. The slice is structurally simple and reactive-correct, but it shares a controller that has outgrown its single responsibility, exposes a downstream service's DTOs directly to clients, and rides on a constants-interface anti-pattern in the SAP integration layer. The most actionable refactors are: **(a) extract `CustomerController`**, **(b) own the response DTO instead of re-exporting `Yggdrasil.*`**, **(c) unify Jackson versions**, and **(d) make authorization on PII endpoints explicit via `Permission`**.
