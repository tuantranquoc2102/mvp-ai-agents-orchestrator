# Architecture

_Agent: `architect` (Software Architect)_  
_Status: `success` · attempts: 1_

---

# Architecture Analysis — `/customer` Feature

## Scope of the feature

Two endpoints expose `/customer` functionality, both nested under `/admin`:

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/admin/customers` | Search customers (type, searchString, paging) |
| `GET` | `/admin/customer`  | Fetch a single customer by `bpNo` + `userId` |

The `Permission` enum also contains a `/customer`-bearing constant (likely an RBAC token), and `SAP.java` declares the downstream endpoints (`/CustomerDetailsRetrieval`, `/MSSLCustomerDetailsRetrieval`, `/CustomerProfileRetrieval`) that satisfy these reads.

## Layering (inferred from the 3 files in scope)

```
┌─────────────────────────────────────────────────────────────┐
│  HTTP edge                                                  │
│  io.spdigital.ubm.admin.controller.AdminController          │  ← Spring WebFlux REST controller (reactive Mono)
└────────────────┬────────────────────────────────────────────┘
                 │ delegates to
┌────────────────▼────────────────────────────────────────────┐
│  Application service                                        │
│  io.spdigital.ubm.admin.service.AdminService (+ UserService)│  ← not in scan; inferred from imports
└────────────────┬────────────────────────────────────────────┘
                 │ orchestrates
        ┌────────┴────────────────────────┐
        ▼                                 ▼
┌──────────────────────┐         ┌────────────────────────────┐
│ SAP integration      │         │ Yggdrasil (user/identity)  │
│ io.spdigital.ubm.    │         │ io.spdigital.ubm.model.dto │
│ service.sap.po.SAP   │         │ .Yggdrasil.SearchCustomers │
│ (POJOs + URI consts) │         │ (transport DTOs)           │
└──────────────────────┘         └────────────────────────────┘

Cross-cutting:
  • io.spdigital.ubm.logging.Loggable                (@Loggable AOP)
  • io.spdigital.ubm.common.{Constants, SecurityContextHeader, UserUtil}
  • io.spdigital.ubm.common.enums.Permission         (RBAC tokens)
  • io.spdigital.ubm.util.{MaskingUtil, SnakeUpperCaseStrategy}
```

**Module / package layout pattern:** the codebase mixes two styles —
- *Feature-by-feature* under `admin.*` (`admin.controller`, `admin.service`, `admin.dto`)
- *Layer-by-layer* / *technology-driven* under `service.sap.*`, `model.dto`, `common.*`, `util`, `logging`.

**External systems:** two downstream integrations are visible from this scope — **SAP** (synchronous request/response over HTTP, JSON in `SNAKE_UPPER_CASE`) and **Yggdrasil** (user/customer identity service).

**Communication style:** reactive HTTP edge (`Mono<…>`). The downstream calls are not visible in this 3-file slice, but for the reactor chain to be honest they must be non-blocking (typically `WebClient`).

---

## Structural smells flagged

1. **God controller.** `AdminController` mixes five unrelated concerns: customer read (`/customer*`), BP-number maintenance (`/bpNos*`), subscription (`/subscription`, `/retrieve/subscription`), user lifecycle (`/users/delink`, `/users/forgot-password`). The `/customer` feature should live in its own controller (e.g. `CustomerController` under `/admin/customers`) so it can evolve, be secured, and be tested independently.

2. **Inverted dependency: infrastructure → feature DTO.** `io.spdigital.ubm.service.sap.po.SAP` imports `io.spdigital.ubm.admin.dto.Subscription`. The SAP integration package (deep infrastructure) is now coupled to a feature-level DTO inside `admin.dto`. This is the wrong direction — the SAP layer must not know about admin DTOs. It will impede future extraction of either module and risks cyclic packages as soon as `admin.*` references `service.sap.*` (which it almost certainly does via `AdminService`).

3. **External transport DTO leaks into the API contract.** The `/admin/customers` endpoint returns `Mono<Yggdrasil.SearchCustomers.Response>` directly. `Yggdrasil` is named after a downstream system — exposing its DTO as the public response binds the public API shape to whatever Yggdrasil sends back. There is no anti-corruption layer / response mapper here. Same risk for `GetCustomerResponse` (need to verify it's not a thin re-export of an SAP POJO).

4. **Mixed Jackson generations.** `SAP.java` imports both `com.fasterxml.jackson.annotation.JsonProperty` (Jackson 2.x) **and** `tools.jackson.databind.annotation.JsonNaming` (Jackson 3.x, `tools.jackson` namespace). Either an in-flight upgrade or an accidental dual-pull — needs reconciliation; behaviour around naming strategies differs between the two.

5. **Authorization not visible at the endpoint.** `Permission` enum carries `/customer` tokens, but neither `getCustomers` nor `getCustomer` has `@PreAuthorize` / `@Secured` / equivalent. Either security is enforced upstream (a global filter or `Loggable`-style AOP that reads `SecurityContextHeader`) or the `/customer` reads are unprotected. Worth confirming explicitly — implicit security is a recurring source of regressions.

6. **No input validation.** `getCustomer(@RequestParam String bpNo, @RequestParam String userId)` has no `@NotBlank`, no length/format constraints, and no `@Validated` on the class. Same for `getCustomers`. Invalid input is currently the downstream system's problem.

7. **Inconsistent reactive error handling.** `getBpNoByAccountNo` defensively uses `.onErrorResume(...)`. `getCustomer` and `getCustomers` don't. Either both should rely on a global `@RestControllerAdvice` (consistent), or both should handle inline — the current mix is incidental.

8. **Wrong/unused import.** The controller imports `org.springframework.web.servlet.function.ServerResponse` — that's the **servlet** package in a WebFlux (Mono-based) controller. Unused, and signals MVC/WebFlux confusion in IDE templates.

9. **Wildcard import.** `org.springframework.web.bind.annotation.*` — minor, but inconsistent with the explicit imports elsewhere in the file.

10. **Log/method name drift.** `getCustomers(...)` logs `"AdminController :: searchCustomers :: Start"`. Cosmetic, but a tell that the method was renamed without updating the log — these strings are commonly grep targets in production triage.

---

## Quick read of risk

| Smell | Severity | Why it matters for `/customer` |
|---|---|---|
| Inverted SAP → admin.dto dep (#2) | **High** | Will cause cycles the moment `admin` imports anything from `service.sap`. |
| Yggdrasil DTO as public response (#3) | **High** | Upstream contract changes ripple to API consumers. |
| Mixed Jackson 2/3 (#4) | **High** | Latent serialization bugs; naming strategy resolution differs. |
| God controller (#1) | Medium | Slows iteration on `/customer`; obscures ownership. |
| Missing `@PreAuthorize` on `/customer*` (#5) | Medium–High pending verification | Authorization may be implicit. |
| Missing validation (#6) | Medium | Errors surface at SAP, not at the edge. |
| Inconsistent error handling (#7) | Low–Medium | Behaviour varies per endpoint. |
| Wrong/unused `ServerResponse` import (#8) | Low | Code smell. |
| Wildcard import (#9), log drift (#10) | Low | Hygiene. |

---

## Notes / gaps

- I was unable to read `SAP.java` (full) and `Permission.java` directly (permission denied); analysis of those two files is based on the truncated content + import set surfaced by the scan. Items #4 (Jackson mix) and #2 (SAP→admin.dto coupling) are confirmed from the visible import list. The exact `/customer`-bearing entries in `Permission` and the full SAP POJO surface (and any blocking calls inside it) would need a follow-up read to fully validate smells #5 and the reactive-honesty concern.
- `AdminService` itself is not in the file scope — the controller→service→SAP/Yggdrasil flow is inferred from imports and signatures. Confirming where the Mono chain actually crosses into blocking code (if anywhere) requires pulling `AdminService` into scope.
