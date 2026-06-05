# Quality

_Agent: `reviewer` (Code Reviewer)_  
_Status: `success` · attempts: 1_

---

# Code Review: `/customer` Feature

**Scope reviewed:** `GET /admin/customer` endpoint (`AdminController.getCustomer`) and its SAP integration constants (`SAP.java`). The scan returned **3 files, 0 tests**.

---

## Summary

The `/customer` endpoint exposes customer PII lookup with **no visible authorization, no input validation, and no test coverage**. The biggest risks are security-shaped (authn/z + PII-in-URL) rather than functional. Code style is clean (Lombok, reactive Mono), but the controller is doing nothing defensive.

---

## HIGH priority

### H1. No visible authorization on a PII-returning endpoint
`AdminController.java:46-50` — `getCustomer(bpNo, userId)` has only `@Loggable` + `@GetMapping`. There is no `@PreAuthorize`, no role check, no `SecurityContextHeader` use, and no manual permission gate against the `Permission` enum that was pulled in by the scan. Anyone who can reach `/admin/**` can read any customer by `bpNo` + `userId`.

- **Fix:** add `@PreAuthorize("hasAuthority('<customer-read-permission>')")` (use the matching constant from `Permission.java`) and verify the `/admin/**` route is behind authenticated security config. Confirm `SecurityContextHeader`/`UserUtil` isn't only used by *other* endpoints in this controller.

### H2. PII in URL query string
`bpNo` and `userId` are passed as `@RequestParam`, so they land in access logs, reverse-proxy logs, APM traces, and browser/history caches. Combined with H1, this is an enumeration + leakage risk.

- **Fix:** either (a) move to `POST /admin/customer/lookup` with a body, or (b) ensure logging filters and proxy configs scrub these params, and add `@Loggable` masking. Cross-check `MaskingUtil` (already imported in `SAP.java`) is applied at the boundary.

### H3. Zero test coverage in the feature scope
No `*Test.java` appeared in the 3 matched files. The endpoint has branching downstream (SAP EBS vs MSSL retrieval paths referenced in `SAP.java`) and no controller/service test demonstrates either path, the empty-result case, or the SAP-error case.

- **Fix:** add at minimum a `@WebFluxTest`-style slice test for happy path + 404/empty + downstream failure, and a service-layer test that mocks the SAP client for EBS vs MSSL routing.

---

## MEDIUM priority

### M1. No input validation on `bpNo` / `userId`
Both are accepted as raw `String` with no `@NotBlank`, `@Size`, or `@Pattern`. Empty strings, very long strings, or characters that downstream SAP/log sinks dislike will flow straight through.

- **Fix:** add `@Validated` on the controller and bean-validation annotations on the params; reject obviously invalid shapes before calling SAP.

### M2. No error handling on the reactive chain
Compare with `getBpNoByAccountNo` (line 60-65), which uses `.onErrorResume`. `getCustomer` returns the raw `Mono<GetCustomerResponse>` — any SAP timeout, 5xx, or parse error will bubble up as a generic 500 with whatever the default exception handler produces, possibly leaking stack traces or internal SAP error strings.

- **Fix:** add an explicit `.onErrorMap` / `.onErrorResume` and a tested global `@RestControllerAdvice` mapping SAP-specific exceptions to sanitized responses.

### M3. Misleading log message
Line 48: `log.info("AdminController :: getCustomerDetails :: Start")` — the method is named `getCustomer`, not `getCustomerDetails`. Small, but it breaks log search/grep and suggests copy-paste from another method.

- **Fix:** align to the method name, or better, include `bpNo`/`userId` (masked) and a correlation id so the log is actually useful.

---

## LOW priority

- **L1. Wildcard import** — `import org.springframework.web.bind.annotation.*;` — explicit imports are the convention elsewhere in the file's imports list.
- **L2. No OpenAPI annotations** — no `@Operation` / `@Parameter`, so `/customer` won't render meaningfully in generated API docs. Consistent with the rest of the controller, but worth fixing at the class level.
- **L3. `ServerResponse` import is unused** (line 23) — dead import, easy cleanup.
- **L4. `SAP.java` mixes two Jackson packages** — `com.fasterxml.jackson.annotation.JsonProperty` alongside `tools.jackson.databind.annotation.JsonNaming` (Jackson 3 namespace). This will compile, but mixing Jackson 2 and Jackson 3 annotations in the same DTO module is a known footgun and a maintainability smell — pick one line.

---

## Notes on coverage of the scan

The scan returned only **3 files**, all production Java, and `SAP.java` was truncated (~30 KB more not shown). Findings about the SAP retrieval DTOs themselves (field-level masking, nullability, snake-case mapping correctness) cannot be made from the visible excerpt. If you want that layer reviewed, re-run with a scan that surfaces the full `SAP.java` and any `CustomerProfileRetrieval`/`CustomerDetailsRetrieval` response classes.
