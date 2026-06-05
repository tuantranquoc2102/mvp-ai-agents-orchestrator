# Architecture

_Agent: `architect` (Software Architect)_  
_Status: `success` · attempts: 1_

---

I'll proceed with the architecture analysis using the input I have (the AdminController source and the file path structure). The `codebase_scan` content was truncated mid-file, so where I'm inferring rather than reading directly I'll flag it.

---

# Architecture Analysis — `/customer` Feature

## 1. Feature Surface

The `/customer` feature is **not** a top-level module — it is one of several endpoints owned by the `admin` module's `AdminController`, mounted under `/admin`:

| HTTP | Path | Handler | Return |
|---|---|---|---|
| GET | `/admin/customers` | `AdminController.getCustomers` | `Mono<Yggdrasil.SearchCustomers.Response>` |
| GET | `/admin/customer` | `AdminController.getCustomer` | `Mono<GetCustomerResponse>` |

Only two endpoints in the scanned controller match `/customer` literally; everything else flagged in the scan (`/bpNos`, `/subscription`, `/users/...`) coexists in the same controller and shares the same service interface. So the architectural unit at play is **the `admin` module**, with `/customer` representing two of its operations.

## 2. Layering (within `io.spdigital.ubm.admin`)

```
admin/
 ├── controller/AdminController        ← HTTP boundary (Spring MVC @RestController, reactive return types)
 ├── service/AdminService              ← Application interface
 ├── service/impl/AdminServiceImpl     ← Orchestration / business logic
 └── dto/                              ← Wire contracts (GetCustomerResponse, UpdateBpNo, Subscription)
```

Classic 3-layer (controller → service interface → service impl) with separate DTO package. Spring stereotypes and Lombok `@RequiredArgsConstructor` indicate constructor-injection throughout — no field injection visible in the controller.

## 3. External Dependencies & Communication Pattern

Inferred from imports and surrounding modules in the scan:

- **Yggdrasil** (`io.spdigital.ubm.model.dto.Yggdrasil.SearchCustomers`) — appears to be an internal "users/identities" service. `/admin/customers` proxies search to it.
- **SAP** (`io.spdigital.ubm.service.sap.po.SAP`) — likely the system of record for business-partner / customer master data behind `getCustomer(bpNo, userId)`.
- **`ReactiveConnectorImpl`** (`config/connector`) — the only reactive HTTP plumbing in scope. Strongly implies all outbound calls are non-blocking `WebClient`-based and that `AdminServiceImpl` composes Yggdrasil + SAP via `Mono`/reactive operators.
- **Auth0** (`config/Auth0Configuration`) — token-based auth at the edge; `SecurityContextHeader` + `UserUtil` propagate principal info downstream.
- **Notification / Holiday / Modification / Profile** modules appear in the scan but are *adjacent* — they share infrastructure (logging, connector) rather than directly serving `/customer`.

Communication style across the codebase: **request/response over reactive HTTP** (Project Reactor `Mono`). No evidence of messaging, eventing, or persistence layer in the `/customer` slice — this is an aggregator/BFF-shaped service.

## 4. Cross-Cutting Concerns

- **`@Loggable` + `LoggableAspect`** — AOP-driven entry/exit logging applied to every controller method.
- **`RequestLoggingDecorator` / `ResponseLoggingDecorator`** — WebFlux server-exchange decorators (likely registered as `WebFilter`s) for raw I/O logging, independent of the AOP layer.
- **`common/Constants`** — pagination defaults injected as `@RequestParam(defaultValue = …)` in the controller.
- **`common/enums/Permission`** — authorization vocabulary; not visible enforced inside the controller methods, which is a smell worth flagging.

## 5. Module Map (feature-relevant)

```
io.spdigital.ubm
 ├── admin/                ← owns /customer
 ├── approvals/            ← parallel feature (own controller)
 ├── reports/              ← parallel feature
 ├── trail/                ← audit trail (parallel)
 ├── modification/         ← parallel
 ├── service/              ← shared downstream clients (sap, notifications, holidays)
 ├── model/dto/            ← cross-module wire types (Yggdrasil, ProfileApi, BaseResponse)
 ├── common/               ← Constants, enums, SecurityContextHeader, UserUtil
 ├── config/               ← Auth0Configuration, connector/ReactiveConnectorImpl
 ├── logging/              ← LoggableAspect, Request/ResponseLoggingDecorator
 └── Application.java      ← Spring Boot entrypoint
```

Dependency direction (observed/inferred): `admin → service/* → config/connector`, and `admin → model/dto`, `admin → common`, `admin → logging`. No reverse edges visible — layering looks acyclic.

## 6. Structural Smells

1. **God controller in the making.** `AdminController` mixes customer search, customer detail, BP-number management, subscription updates, user delinking, and password recovery. `/customer` and `/customers` already live there alongside ~7 unrelated concerns. `AdminService` almost certainly mirrors this and is becoming a god interface. Split candidates: `CustomerController`, `BpNoController`, `SubscriptionController`, `UserAccountController`.

2. **Wire types from a foreign bounded context leak into the controller signature.** `getCustomers` returns `Mono<Yggdrasil.SearchCustomers.Response>` directly — i.e. the downstream provider's DTO is the public API contract. Any change in Yggdrasil ripples straight to API clients. By contrast, `/customer` correctly returns `GetCustomerResponse` (an admin-owned DTO). Inconsistent and a coupling hazard.

3. **Nested wire DTOs (`Yggdrasil.SearchCustomers`, `UpdateBpNo.Request`, `Subscription.Update.Request`, `Subscription.Retrieve.Request`).** Nested classes inside DTO holders is a stylistic choice, but it makes evolution and JSON-schema generation awkward and tends to grow into deeply nested static-class soup.

4. **No visible authorization on `/customer`.** `Permission` enum exists in `common/enums`, but the controller methods carry no `@PreAuthorize` / explicit check. Either it lives in a `WebFilter`/`SecurityWebFilterChain` (not in scope) or it's missing. For an admin endpoint that takes arbitrary `bpNo` and `userId` as query params, this needs verification — it's a likely IDOR surface.

5. **Inconsistent error handling.** `getBpNoByAccountNo` swallows errors into a 204; `getCustomer` has no `onErrorResume` and will surface raw reactor failures to the default Spring error mapper. Two different conventions in one controller.

6. **`/admin/customer` returns a single record keyed by `(bpNo, userId)` — both as query params.** Sensitive identifiers in the URL line get logged by `RequestLoggingDecorator` unless that decorator is PII-aware. Worth auditing.

7. **`UserService` injected but unused in scanned methods.** Either dead wire-up for `/customer` slice or the broader controller couples two services that should be split.

8. **Mixing `Mono` and `ServerResponse` imports** in one controller (`org.springframework.web.servlet.function.ServerResponse` alongside reactive types) — `ServerResponse` from the **servlet** package is unused in the shown code but its presence hints at a copy-paste; if it ever gets used, it'll mix the blocking and reactive stacks, which is the canonical WebFlux footgun.

## 7. What I Could Not Verify (read access denied)

- `AdminService` / `AdminServiceImpl` bodies — actual orchestration of Yggdrasil+SAP calls, error mapping, and any caching.
- `GetCustomerResponse` shape — whether it's a thin pass-through or a real aggregation DTO.
- `AdminServiceImplTest` — coverage and whether `/customer` paths are exercised.
- `ReactiveConnectorImpl` — timeout/retry/circuit-breaker posture for downstream calls.
- `Auth0Configuration` — where authorization actually happens (filter chain vs. method security).

Recommend pulling these four into the next inspection pass before the design-doc phase commits to a refactor plan.
