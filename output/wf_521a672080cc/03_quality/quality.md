# Quality

_Agent: `reviewer` (Code Reviewer)_  
_Status: `success` · attempts: 1_

---

# Code Review — `/customer` Feature

**Scope reviewed:** 3 files, 22.3 KB, all Java
- `AdminController.java` (the `/customer` + `/customers` endpoints)
- `SAP.java` (customer-related SAP integration constants/DTOs)
- `Permission.java` (referenced; content not viewable — see Medium-3 below)

> Note: I attempted to read the full `SAP.java` and `Permission.java` to verify masking/permission enforcement but read permission was denied. Findings below are based on `AdminController.java` (full) and the visible portion of `SAP.java`. Items that depend on the unread files are explicitly flagged.

---

## HIGH severity

### H1. No authorization enforcement on customer endpoints
`AdminController` exposes `GET /admin/customer` and `GET /admin/customers` but neither method (nor the class) carries `@PreAuthorize`, `@Secured`, or any visible role check. A `Permission` enum is in scope for the feature, yet it appears nowhere in this controller — so either authorization happens in a filter (please verify) or these endpoints are unprotected. For an "admin" surface that returns customer PII by `bpNo`/`userId`, missing method-level auth is a critical gap.

**Fix:** Add `@PreAuthorize("hasAuthority('CUSTOMER_READ')")` (or the matching `Permission` value) on `getCustomer` and `getCustomers`. Even with a security filter, defense-in-depth at the method is standard.

### H2. No input validation on customer query parameters
```java
public Mono<GetCustomerResponse> getCustomer(@RequestParam String bpNo, @RequestParam String userId)
public Mono<...> getCustomers(@RequestParam String type, @RequestParam String searchString, ...)
```
- No `@NotBlank`, no length limits, no regex on `bpNo` / `userId` / `type`.
- `searchString` is forwarded to a downstream service (likely SAP or a DB query) with zero sanitization — injection/abuse risk depends on the sink.
- `direction` accepts any string; only `ASC`/`DESC` should be valid.
- `type` is a free-form string but almost certainly maps to an enum.

**Fix:** Use `@Validated` on the class plus `@NotBlank @Size(max=…) @Pattern(...)` on each parameter; convert `type` and `direction` to enums so Spring rejects bad values at the boundary.

### H3. Unbounded pagination — resource exhaustion
`pageSize` comes from `DEFAULT_PAGE_SIZE` but has no max bound. A caller can request `pageSize=100000` and force a large SAP/DB fetch plus a large response payload.

**Fix:** Add `@Max(100)` (or your policy ceiling) on `pageSize`, and `@Min(0)` on `pageNumber`. Reject negative values explicitly.

### H4. PII in logs via `@Loggable` (verify masking)
Both customer methods are annotated `@Loggable`, and `bpNo` + `userId` are identifiers tied to a person. `SAP.java` imports `MaskingUtil`, which suggests masking exists *somewhere*, but `@Loggable` is on the controller method and likely logs raw parameter values. If `@Loggable` doesn't apply masking to request params, this is a PDPA/GDPR-class issue.

**Fix:** Confirm `@Loggable` masks `bpNo`, `userId`, account numbers, emails. If it doesn't, either add masking to the aspect, or remove `@Loggable` from these methods and log a sanitized message manually (as `getBpNoByAccountNo` already does).

---

## MEDIUM severity

### M1. Inconsistent reactive error handling
`getBpNoByAccountNo` handles errors with `onErrorResume` and returns `204 No Content` on failure — which is itself questionable (swallowing all errors hides bugs and returns success-class status for failures). Meanwhile `getCustomer` and `getCustomers` have no error handling at all, so any downstream failure bubbles up as a generic 500.

**Fix:** Standardize on a `@RestControllerAdvice` that maps domain exceptions to HTTP status codes. Do not swallow errors silently in `onErrorResume`; only translate expected ones (e.g., `NotFoundException -> 404`).

### M2. No HTTP-method-level idempotency / cache semantics declared
`GET /customer` returns sensitive data — no `Cache-Control: no-store` is enforced at the controller level. For PII-bearing GETs, browser/proxy caching should be explicitly disabled.

### M3. `Permission` enum is in feature scope but not referenced here
The scan pulled `Permission.java` because it mentions `/customer`, but `AdminController` never imports or uses it. Two possibilities — both worth checking:
- The enum defines `CUSTOMER_*` permissions that *should* be enforced on these endpoints but aren't wired up (ties to H1).
- The constants are stale/dead code.

I couldn't read `Permission.java` to confirm — please open it and verify whether `CUSTOMER_READ`/`CUSTOMER_SEARCH` (or similar) exist and whether they're enforced anywhere.

### M4. Controller violates SRP & is growing into a god class
`AdminController` already mixes customers, bpNos, subscriptions, user delink, and forgot-password. As the `/customer` surface grows it'll get worse. Consider splitting into `CustomerController`, `BpNoController`, `SubscriptionController`.

### M5. Wildcard import
```java
import org.springframework.web.bind.annotation.*;
```
Project convention almost certainly forbids this; checkstyle/spotbugs would flag it.

### M6. No tests for the `/customer` feature in scope
The scan returned 3 files, none of them tests. Either the scan filter excluded tests (likely) or there are no controller/service tests asserting:
- 200 happy path for `getCustomer` / `getCustomers`
- Validation rejection (once added)
- Authorization rejection (once added)
- Downstream error → correct status mapping

**Action:** Confirm `AdminControllerTest` / `AdminServiceTest` exist and exercise these two endpoints. If not, add `@WebFluxTest` slice tests.

---

## LOW severity

### L1. Log message style is inconsistent
`"AdminController :: searchCustomers :: Start"` vs `"Retrieving subscription information..."` vs no log at all. Pick one style (preferably structured logging with MDC) and apply it uniformly. Also note `getCustomer`'s log line says `"getCustomerDetails"` — method name drift.

### L2. `@RequestParam` defaults are stringly-typed
`DEFAULT_PAGE_NUMBER`, `DEFAULT_PAGE_SIZE`, `DEFAULT_SORT_DIRECTION` are `String` constants because `@RequestParam(defaultValue=...)` requires it, which is fine — but ensure the constants match the validation bounds you add in H3 (e.g., default isn't above max).

### L3. `SAP.java` mixes interface-as-constants pattern with rich DTOs
Putting String endpoint constants on an interface alongside `@Value`/`@Data` nested types is a legacy pattern. Consider extracting endpoint paths into a `SapEndpoints` final class and keeping DTOs in their own files. Low priority — purely organizational.

### L4. `BaseResponse` / `Mono<BaseResponse>` vs `ResponseEntity<...>`
The controller mixes raw response types (`Mono<GetCustomerResponse>`) and `Mono<ResponseEntity<...>>`. Pick one approach for consistency; raw types are cleaner when paired with a `@RestControllerAdvice`.

---

## Quick punch list (priority order)

1. **H1** — Add `@PreAuthorize` to `getCustomer` / `getCustomers`, wire to `Permission` enum.
2. **H4** — Audit `@Loggable` masking of `bpNo`/`userId`; remove or mask if leaking.
3. **H2 / H3** — Add `@Validated`, bean-validation annotations, `@Max` on `pageSize`, enums for `type`/`direction`.
4. **M3** — Read `Permission.java` and confirm CUSTOMER permissions exist and are enforced somewhere.
5. **M6** — Verify test coverage for the two `/customer` endpoints; add slice tests if missing.
6. **M1** — Replace silent `onErrorResume` swallowing with a `@RestControllerAdvice`.
7. **M5 / L1 / L4** — Style cleanup (wildcard import, log format, response-type consistency).
