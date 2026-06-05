# Architecture

_Agent: `architect` (Software Architect)_  
_Status: `success` · attempts: 1_

---

# Architecture Analysis — `/customer` Feature

## Scope
Two HTTP endpoints touch the customer concept in this feature slice:

| Method | Path | Handler |
|---|---|---|
| GET | `/admin/customer` | `AdminController#getCustomer(bpNo, userId)` |
| GET | `/admin/customers` | `AdminController#getCustomers(type, searchString, pageNumber, pageSize, direction)` |

Three files are in scope: `AdminController.java`, `service/sap/po/SAP.java`, and `common/enums/Permission.java` (content not visible — read denied, so I treat it as the authorization vocabulary used elsewhere).

## Layering & Modules

The feature follows a conventional **layered (controller → service → integration)** topology, built on **Spring WebFlux** (everything returns `Mono<…>`):

```
io.spdigital.ubm
├── admin
│   ├── controller          ← AdminController (web layer)
│   │   └── @RestController("/admin")
│   ├── service             ← AdminService, UserService (business orchestration)
│   └── dto                 ← GetCustomerResponse, Subscription, UpdateBpNo
├── service.sap.po          ← SAP integration DTOs/payload objects (PO = payload object)
│   └── SAP (interface — endpoint path constants)
├── model.dto               ← shared response envelopes (BaseResponse, Yggdrasil.SearchCustomers)
├── common
│   ├── Constants           ← DEFAULT_PAGE_NUMBER/SIZE/SORT_DIRECTION
│   ├── SecurityContextHeader, UserUtil
│   └── enums.Permission    ← authorization vocabulary
├── logging                 ← @Loggable cross-cutting aspect
└── util                    ← MaskingUtil, SnakeUpperCaseStrategy (Jackson naming)
```

## Communication & External Dependencies

- **Inbound:** REST/JSON over HTTP via Spring WebFlux (reactive, non-blocking).
- **Outbound (downstream of `AdminService`):** SAP back-office. The `SAP` interface enumerates the integration surface used by the customer flow:
  - `/CustomerDetailsRetrieval` (EBS — Electricity Business System)
  - `/MSSLCustomerDetailsRetrieval` (MSSL — Singapore gas/meter operator variant)
  - `/CustomerProfileRetrieval`
  - `/UpdateBillPreference`, etc.
- **Cross-cutting:** `@Loggable` AOP, Lombok for boilerplate, Jackson with a custom `SnakeUpperCaseStrategy` (SAP wire format), `MaskingUtil` for PII redaction in logs.
- **Identity model:** `bpNo` (SAP Business Partner number) + `userId` are the composite keys threaded through every customer-related operation.

The controller surface suggests **two upstream consumers**: an admin UI (search/lookup, BP↔account/user mappings, subscription, delink) and SAP downstream (customer/bill data of record).

## Structural Smells

1. **God controller.** `AdminController` mixes at least five concerns: customer search/read, BP↔account/user mapping, subscription read/update, user delink, and forgot-password. The `/customer` feature is wedged into this catch-all; it should live in a dedicated `CustomerController` (or under a `customer` sub-package mirroring `admin`).
2. **Layer leak into the SAP integration package.** `service.sap.po.SAP` imports `io.spdigital.ubm.admin.dto.Subscription`. The SAP wire-model module should not depend on an admin-layer DTO — the dependency arrow points the wrong way (integration → app layer). Introduce a neutral domain/contract type or an SAP-side `SubscriptionPayload` and translate at the service boundary.
3. **URI/responsibility mismatch.** `/admin/customer` is a customer read operation parked under the `/admin` namespace. If non-admin clients also need customer data this will force duplication; if only admin needs it, the controller name/contents are still doing too much (see #1).
4. **Composite required identifier without a contract.** `getCustomer(@RequestParam String bpNo, @RequestParam String userId)` makes both params mandatory query strings with no validation, no `@NotBlank`, and no documented invariant (do they have to belong to each other? is one derivable from the other?). Easy to misuse from the client side.
5. **Inconsistent operation naming.** Log lines say `searchCustomers` and `getCustomerDetails`, while methods are `getCustomers` and `getCustomer`. Either the method names understate the behaviour (`getCustomers` is actually a paged search) or the logs lie. Rename to `searchCustomers` / `getCustomerDetails` to match intent.
6. **Wildcard import** (`org.springframework.web.bind.annotation.*`) — minor, but inconsistent with the rest of the explicit imports.
7. **Unverified authorization.** `Permission` is in scope of the feature query but is not referenced from `AdminController` — no `@PreAuthorize` or equivalent on `/customer`/`/customers`. Either authz is enforced at a gateway/filter level (worth documenting) or it is missing for an admin-only resource that returns PII.
8. **`Yggdrasil.SearchCustomers.Response` as the response envelope.** The customer search response leaks a mythologically-named cross-cutting model out of the admin layer; if `Yggdrasil` is a sibling identity/customer service, the response shape couples the controller to that service's wire model rather than a stable API contract.
9. **No DTO for the `/customer` query.** Two raw `@RequestParam`s instead of a small request record — fine today, awkward when filters grow.

## Recommended Moves (high-leverage, low-risk)

- Split `AdminController` along boundaries: `CustomerAdminController` (`/admin/customer[s]`), `BpNoController`, `SubscriptionController`, `UserAdminController`. Keeps the `/customer` feature self-contained.
- Invert the `SAP → admin.dto.Subscription` dependency: define the SAP payload in `service.sap.po` and map to/from `admin.dto.Subscription` inside `AdminService`.
- Add `@Validated` + `@NotBlank` (or a small `GetCustomerRequest` record) on `/customer`.
- Make the authz story explicit on the customer endpoints (`@PreAuthorize("hasAuthority(T(Permission).CUSTOMER_READ)")` or equivalent), referencing the `Permission` enum that is already in the feature scope.
- Align method names with logs (`searchCustomers`, `getCustomerDetails`).
