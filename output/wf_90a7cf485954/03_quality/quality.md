# Quality

_Agent: `reviewer` (Code Reviewer)_  
_Status: `success` · attempts: 1_

---

# Code Review: `/customer` Feature

## Scope
Reviewed 3 Java files referencing `/customer`:
- `AdminController.java` (full content visible)
- `SAP.java` (truncated at ~15KB — constants/DTOs for SAP integration)
- `Permission.java` (not visible in content payload, only listed)

Findings below are based strictly on what is observable in the provided slices. Items requiring code I cannot see are flagged.

---

## High-Priority Findings

### H1. Missing authorization on `/customer` and `/customers` endpoints
`AdminController.getCustomer(...)` and `getCustomers(...)` accept `bpNo` and `userId` purely as `@RequestParam`s with no visible authorization check (no `@PreAuthorize`, no manual permission gate, no use of `SecurityContextHeader`/`UserUtil` that are imported but unused in this file).

- Risk: **IDOR (Insecure Direct Object Reference)**. Any authenticated caller who can hit `/admin/customer?bpNo=...&userId=...` can pull arbitrary customer data by guessing/iterating identifiers.
- The class is under `/admin` and a `Permission` enum exists in scope — strongly suggests RBAC was intended but not wired here.
- Action: confirm whether a global `WebSecurityConfig`/method-security advice enforces admin role on `/admin/**`. If not, add `@PreAuthorize("hasAuthority('ADMIN_CUSTOMER_READ')")` (or equivalent from `Permission`).

### H2. Unvalidated query parameters
`getCustomers` accepts `type`, `searchString`, `pageNumber`, `pageSize`, `direction` as raw strings/ints with no `@Valid`, no `@Pattern`, no upper bound on `pageSize`, and no enum binding on `direction`/`type`.

- Risk: enumeration attacks, excessive-result DoS (caller sets `pageSize=1000000`), downstream SAP/Yggdrasil call amplification.
- Action: cap `pageSize` (e.g., `@Max(100)`), bind `direction` to `Sort.Direction` enum or a whitelist, validate `type` against an enum, escape/limit `searchString`.

### H3. Personally Identifiable data via GET query string
`bpNo`, `userId`, `email` (forgotPassword), `accountNo` are all transmitted as URL parameters. These end up in access logs, proxy logs, browser history, and APM traces.

- Risk: PII leakage; complicates GDPR/PDPA handling.
- Action: log scrubbing for these params (does `@Loggable` already mask? — not visible). Consider POST with body for lookups carrying PII, or confirm masking in the logging aspect.

---

## Medium-Priority Findings

### M1. Unused imports in `AdminController` suggest dead/half-built security plumbing
`SecurityContextHeader` and `UserUtil` are imported but never referenced. Either:
- they were the intended authorization hook and removed during a refactor (regression), or
- they are leftover dead imports.

Either way, this is a smell on a sensitive admin controller. Verify intent.

### M2. Inconsistent error handling
`getBpNoByAccountNo` swallows **all** errors and returns `204 No Content` (`onErrorResume(e -> Mono.just(ResponseEntity.noContent().build()))`).

- Hides 5xx infrastructure failures as "not found".
- Inconsistent with sibling methods (`getCustomer`, `getCustomers`) which surface errors normally.
- Action: differentiate `NotFoundException` (→ 404/204) from generic `Throwable` (→ 5xx). Log the exception.

### M3. Logging style: start-only logs, no correlation
Logs say `":: Start"` but there is no matching `":: End"` or outcome log, and no obvious correlation/trace id propagation in this controller layer (may be handled by `@Loggable`/MDC — not visible).

- Action: ensure `@Loggable` AOP emits both entry and exit with duration and a correlation id; otherwise add structured logging.

### M4. Test coverage signal: none visible
The scan returned **zero test files** for this feature (`file_count: 3`, all production sources). No `AdminControllerTest`, no integration test reference, no contract test for the SAP `/CustomerDetailsRetrieval` or `/MSSLCustomerDetailsRetrieval` calls.

- Risk: a sensitive admin endpoint touching SAP and customer PII has no observable regression safety net.
- Action: add `@WebFluxTest`/`WebTestClient` slice tests covering auth, validation, happy path, downstream failure, and PII masking.

### M5. Wildcard import
`import org.springframework.web.bind.annotation.*;` — minor style issue but flagged in many enterprise Java standards (and inconsistent with the explicit imports elsewhere in the file).

---

## Low-Priority Findings

### L1. Mixed mapping styles
Some `@GetMapping(value = "/customer")` use the `value =` attribute; others use the shorthand `@PostMapping("/bpNos")`. Trivial consistency nit.

### L2. `ServerResponse` import unused
`import org.springframework.web.servlet.function.ServerResponse;` is imported but not used. Dead import.

### L3. SAP.java path constants are hand-typed strings
`EBS_CUSTOMER_DETAILS_RETRIEVAL`, `MSSL_CUSTOMER_DETAILS_RETRIEVAL`, etc., are loose `String` constants on an interface. Acceptable, but a typed enum or `record`-backed config would be safer if any of these vary by environment.

### L4. `MaskingUtil` referenced in `SAP.java`
Good signal that PII masking exists somewhere — but the truncated portion may show whether it is actually applied to customer fields in DTOs. Verify masking covers NRIC/passport/email/phone in `GetCustomerResponse` and `Subscription.*`.

---

## Maintainability Summary

| Aspect | Signal |
|---|---|
| Controller cohesion | Mixed — `AdminController` bundles customer lookup, BP-number management, subscriptions, delink, and forgot-password. Consider splitting `CustomerAdminController` out. |
| DTO discoverability | DTOs nested in `Yggdrasil.SearchCustomers.Response` and `Subscription.Retrieve.*` — deep nesting hurts readability. |
| Reactive consistency | All methods return `Mono<...>` ✔. |
| Auth wiring | **Not visible in this slice — biggest open question.** |
| Tests | **None present in feature scope — biggest gap.** |

---

## Recommended Next Actions (in order)

1. **Confirm authorization** is enforced on `/admin/**` globally; if not, add method-level `@PreAuthorize` referencing `Permission`.
2. **Add input validation** to `getCustomers` (page-size cap, direction whitelist, type enum).
3. **Write tests** for `getCustomer`/`getCustomers` covering auth failure, validation failure, downstream SAP error, and PII masking in the response body and logs.
4. **Fix error swallowing** in `getBpNoByAccountNo`.
5. **Clean up dead imports** (`SecurityContextHeader`, `UserUtil`, `ServerResponse`) — or wire them up if they were intended.

## Items I Could Not Verify (need access)
- `Permission.java` content — to confirm which permission constants exist for customer reads.
- `AdminService.getCustomer` / `getCustomers` implementation — for SQL injection / SAP request construction / response masking.
- Truncated portion of `SAP.java` — for DTO masking annotations.
- Global security configuration — to resolve H1 definitively.
