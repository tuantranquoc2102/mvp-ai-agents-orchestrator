# Quality

_Agent: `reviewer` (Code Reviewer)_  
_Status: `success` · attempts: 1_

---

# Code Review: `/customer` Feature

**Scope reviewed:** 3 files (~22KB Java) — `AdminController.java`, `SAP.java`, `Permission.java`. Note: `SAP.java` content was truncated in the input (only ~2KB of 15KB visible) and `Permission.java` was not visible at all in the excerpt, so findings on those files are limited to what was readable.

---

## HIGH severity

### H1. No authorization check on `/admin/customer` and `/admin/customers` endpoints
`AdminController.java:36-50` — Both endpoints are mounted under `/admin` but the controller methods have **no** `@PreAuthorize`, `@Secured`, or equivalent method-level authorization. Looking up arbitrary customer details by `bpNo` + `userId` is a classic BOLA / IDOR vector if route-level security in `SecurityConfig` is misconfigured or missing. The fact that `Permission.java` exists in the matched-files set strongly suggests there is an intended RBAC model that simply isn't being applied here.

**Fix:** Add `@PreAuthorize("hasAuthority('CUSTOMER_READ')")` (or whichever `Permission` enum constant applies) directly on the handler methods. Defense-in-depth — don't rely solely on a global config.

### H2. No input validation on customer lookup parameters
`AdminController.java:38-39, 47`
```java
public Mono<SearchCustomers.Response> getCustomers(@RequestParam String type, @RequestParam String searchString, ...)
public Mono<GetCustomerResponse> getCustomer(@RequestParam String bpNo, @RequestParam String userId)
```
No `@NotBlank`, `@Pattern`, `@Size`, or `@Valid`. `searchString` is fed straight into downstream search — if SAP/Yggdrasil uses any kind of templated query, this could allow injection or excessive-result DoS. `bpNo` / `userId` formats are not constrained.

**Fix:** Add bean validation annotations and `@Validated` on the controller. Constrain `type` to an enum.

### H3. Unbounded `pageSize`
`AdminController.java:40` — `pageSize` defaulted from `Constants.DEFAULT_PAGE_SIZE` but no upper bound. A caller passing `pageSize=100000` will cause a fanout to SAP and potentially memory pressure. For an admin endpoint that returns PII this is both a performance and data-exposure risk.

**Fix:** Validate `@Max(100)` (or whatever the product cap is) on `pageSize`.

---

## MEDIUM severity

### M1. Error swallowing on `/bpNos/accountNo/{accountNo}`
`AdminController.java:62-64`
```java
.onErrorResume(e -> Mono.just(ResponseEntity.noContent().build()));
```
Every error — network failure, downstream 5xx, auth failure — is collapsed to `204 No Content`. Callers can't distinguish "no result" from "downstream broken," and the error is not logged. This hides outages and complicates incident triage.

**Fix:** Log the error at WARN/ERROR and map by exception type; only convert genuine not-found cases to 204 (or better, 404).

### M2. No visible tests for the `/customer` feature
The feature scope contains zero test files. Either the scanner is excluding tests or there are none. For an endpoint that returns customer PII via SAP integration, the absence of controller slice tests (`@WebFluxTest`) and integration tests is a real quality risk.

**Action:** Verify with `Glob: **/AdminController*Test.java` — if missing, add tests covering: happy path, missing/blank params (validation), authorization denial, and downstream-error mapping.

### M3. PII in request parameters and logs
`AdminController.java:42, 48` — `searchString`, `bpNo`, `userId` flow through a controller annotated `@Loggable` (custom logging aspect) and reach `log.info(...)` calls. Depending on what `@Loggable` records, full request params (including a search string that may contain partial NRIC / email / phone) may end up in application logs. Note `SAP.java` imports `MaskingUtil` — good — but that masking is downstream-only; controller-level logging may already have captured the unmasked value.

**Action:** Audit the `@Loggable` aspect to ensure it does not log request params for these handlers, or apply field-level masking before logging.

### M4. Wildcard import & dead import
`AdminController.java:22` uses `org.springframework.web.bind.annotation.*` — discouraged by most style guides; makes diffs noisier when annotations change.
`AdminController.java:23` imports `org.springframework.web.servlet.function.ServerResponse` which is **unused** *and* is the servlet (blocking) variant in a WebFlux (`Mono<>`) controller — a copy-paste tell that someone might wire blocking code here later.

**Fix:** Remove the unused import; expand the wildcard.

---

## LOW severity

### L1. Inconsistent / low-signal log messages
`AdminController.java:41, 48, 61, 68, 74, 80, 89` — Mix of `"AdminController :: searchCustomers :: Start"` (start markers, no end markers, no correlation id in message) and free-form `"Retrieving bpNo by AccountNo information..."`. Logs do not include `bpNo`/`userId` (which is good for PII, see M3) but also don't include any correlation id, so tracing a single `/customer` call across logs requires MDC/Sleuth being configured elsewhere.

**Suggestion:** Standardize on structured logging (key-value) and rely on the `@Loggable` aspect for entry/exit rather than mixing manual `log.info`.

### L2. `getCustomers` query-string contract is brittle
`type` and `direction` are free-form `String`. The compiler can't catch a typo and Swagger/OpenAPI consumers get no enum hint.

**Suggestion:** Bind `direction` to `Sort.Direction` and `type` to a domain enum; Spring will auto-validate.

### L3. `SAP.java` constants — minor
From the visible portion: route constants are defined on an interface (fine for grouping), but using a `public interface` purely as a constant container is a Joshua-Bloch-flagged anti-pattern. Prefer a `final class` with a private constructor or a record-style holder.

---

## Coverage / maintainability summary

| Dimension | Status |
|---|---|
| Authorization on customer endpoints | **Not visible in feature scope — verify externally (H1)** |
| Input validation | Absent (H2) |
| Pagination bounds | Absent (H3) |
| Error mapping | Lossy on one endpoint (M1) |
| Test coverage for `/customer` | **None in scope (M2)** |
| PII handling | Masking exists downstream; controller-side logging risk (M3) |

---

## Recommended next steps (priority order)

1. **Verify** whether `SecurityConfig` actually gates `/admin/**` with a role check, then add method-level `@PreAuthorize` regardless.
2. Add `@Validated` + bean-validation annotations on `getCustomer` / `getCustomers` parameters; cap `pageSize`.
3. Add a `@WebFluxTest(AdminController.class)` covering the two `/customer` handlers — validation, auth, happy path, downstream error.
4. Audit the `@Loggable` aspect's behavior with respect to PII params.
5. Replace `onErrorResume → 204` in `getBpNoByAccountNo` with typed error mapping + logging.

Flagging that **`SAP.java` and `Permission.java` were truncated/missing in the scan payload**, so any finding requiring their full bodies (e.g., whether a `CUSTOMER_*` permission constant exists, whether SAP DTOs leak unmasked fields) could not be conclusively assessed from these inputs alone.
