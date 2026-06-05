# Architecture

_Agent: `architect` (Software Architect)_  
_Status: `success` · attempts: 1_

---

# Architecture Analysis — `/customer` Feature

## Scope of Evidence
Three files matched the `/customer` feature filter; analysis is restricted to them.

| File | Role |
|---|---|
| `admin/controller/AdminController.java` | HTTP entry point (Spring WebFlux REST controller) |
| `service/sap/po/SAP.java` | SAP backend integration contract — URI constants + payload objects (PO = Protocol Object) |
| `common/enums/Permission.java` | Authorization permission enum (content truncated in input) |

## Layering Inferred

```
┌─────────────────────────────────────────────────┐
│  HTTP Layer            AdminController          │
│  (Spring WebFlux)      @RestController /admin   │
└───────────────┬─────────────────────────────────┘
                │ Mono<GetCustomerResponse>
                ▼
┌─────────────────────────────────────────────────┐
│  Application Layer     AdminService             │
│                        UserService              │
│                        (interfaces only — impl  │
│                         not in feature scope)   │
└───────────────┬─────────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────────────┐
│  Integration Layer     service.sap.po.SAP       │
│                        URI constants + DTOs     │
│                        (CustomerDetailsRetrieval,│
│                         MSSLCustomerDetails…)   │
└───────────────┬─────────────────────────────────┘
                │ HTTP (reactive WebClient — inferred)
                ▼
        ┌──────────────────┐
        │  SAP EBS / MSSL  │   external system
        └──────────────────┘
```

Clear 3-layer separation: **controller → service → SAP PO adapter**. Reactive end-to-end (`Mono<…>`), idiomatic Spring WebFlux.

## `/customer` Surface

Two endpoints belong directly to this feature:

| Method | Path | Handler | Downstream |
|---|---|---|---|
| `GET` | `/admin/customers` | `adminService.getCustomers(type, searchString, pageNumber, pageSize, direction)` → `Yggdrasil.SearchCustomers.Response` | Yggdrasil model (user/identity), paginated |
| `GET` | `/admin/customer` | `adminService.getCustomer(bpNo, userId)` → `GetCustomerResponse` | SAP `CustomerDetailsRetrieval` / `MSSLCustomerDetailsRetrieval` |

Note the path under `@RequestMapping("/admin")` — the literal `/customer` resource is namespaced under the admin context, so it is an **admin-facing customer lookup**, not a customer self-service surface.

## Modules & Packages Touched

- `io.spdigital.ubm.admin.*` — admin-bounded context (controller, dto, service)
- `io.spdigital.ubm.service.sap.po` — SAP integration adapter (Protocol Objects)
- `io.spdigital.ubm.common` — cross-cutting (`Constants`, `SecurityContextHeader`, `UserUtil`, `enums.Permission`)
- `io.spdigital.ubm.model.dto` — shared DTOs (`BaseResponse`, `Yggdrasil`)
- `io.spdigital.ubm.logging` — `@Loggable` cross-cutting concern (AOP)
- `io.spdigital.ubm.util` — `MaskingUtil`, `SnakeUpperCaseStrategy` (PII masking + SAP naming)

## External Dependencies (Customer Path)

- **SAP** — two flavors: standard EBS (`/CustomerDetailsRetrieval`) and MSSL (`/MSSLCustomerDetailsRetrieval`). Two retrieval variants behind one logical "get customer" call suggest a **conditional dispatcher** in `AdminService` based on customer segment.
- **Yggdrasil** — internal user/identity service (model lives in `model.dto.Yggdrasil`). Used by the search flow.
- **Jackson** — serialization. Mixed imports: `com.fasterxml.jackson.annotation.JsonProperty` plus the newer `tools.jackson.databind.annotation.JsonNaming` (Jackson 3 namespace) on the same file — see smells.
- **Lombok** — `@Data`, `@Value`, `@Builder`, `@SuperBuilder`, `@RequiredArgsConstructor`.

## Communication Style

- **Inbound:** REST/JSON, query-param-driven for both customer endpoints.
- **Outbound:** Reactive non-blocking (`Mono`) — implies `WebClient` for SAP & Yggdrasil calls.
- **Cross-cutting:** `@Loggable` annotation-driven AOP for every customer endpoint.
- **Security context:** `SecurityContextHeader` + `Permission` enum referenced from `common` — RBAC enforced upstream (likely filter / method-security), not visible in controller body.

## Structural Smells

1. **Mixed Jackson namespaces in `SAP.java`** — `com.fasterxml.jackson.annotation.JsonProperty` together with `tools.jackson.databind.annotation.JsonNaming`. This is a Jackson 2 ↔ Jackson 3 mix. At runtime one of them is a no-op; this will silently break snake_case mapping for SAP payloads. **High-priority bug risk.**
2. **God interface in `SAP.java`** — a single `SAP` interface aggregates URI constants for `CustomerDetailsRetrieval`, `MSSLCustomerDetailsRetrieval`, `UpdateBillPreference`, `CustomerProfileRetrieval`, plus *PO classes embedded in the interface* (`@Builder`, `@Data` `Value`-typed nested classes). This blends three concerns: routing constants, request DTOs, response DTOs. Recommend splitting into `SapEndpoints` (constants), `sap.po.customer.*` (PO classes per use-case), keep `SAP.java` as a thin marker if needed.
3. **God controller** — `AdminController` mixes customer search, customer detail, BP-number management, subscription read/write, user delink, and forgot-password. Eight endpoints, four bounded sub-domains. The `/customer` feature is coupled to unrelated user-management code through shared service injection. Splitting into `CustomerAdminController`, `BpAdminController`, `SubscriptionAdminController`, `UserAdminController` would isolate the feature.
4. **Cross-feature DTO leakage** — `GetCustomerResponse` lives in `admin.dto`, but `Subscription` (also `admin.dto`) is reused by `service.sap.po.SAP.java`. The SAP integration layer thus depends on the admin layer's DTO, **inverting the intended dependency direction** (integration should not depend on application/admin). This is a latent cyclic-risk between `admin.dto` ⇄ `service.sap.po`.
5. **No request validation** — `@RequestParam String bpNo`, `@RequestParam String userId` lack `@NotBlank` / `@Pattern`. Invalid inputs reach the SAP boundary unfiltered.
6. **Two retrieval URIs, one method** — `getCustomer(bpNo, userId)` resolves both EBS and MSSL paths somewhere downstream. The selection logic is invisible at the contract boundary; surfacing customer-type in the API (or splitting endpoints) would make it explicit.
7. **Permission enum imported but enforcement not visible** — security wiring depends on infra outside the controller; risk of an endpoint shipping without `@PreAuthorize` (or equivalent). Worth auditing whether `GET /admin/customer` and `GET /admin/customers` are actually gated by a `Permission` value.

## Bottom Line

The `/customer` slice follows a clean reactive controller → service → SAP-adapter pattern, but it is embedded in an over-broad admin controller and an overloaded SAP integration interface. The most urgent concrete issue is the **Jackson 2/3 mixed import in `SAP.java`**, which is a correctness bug, not a style issue. The most strategic refactor is **splitting `AdminController` and the `SAP` interface along bounded-context lines** so the customer feature can evolve independently.
