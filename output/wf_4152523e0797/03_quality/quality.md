# Quality

_Agent: `reviewer` (Code Reviewer)_  
_Status: `success` · attempts: 1_

---

# Code Review — `/customer` Feature

Note on scope: I was unable to expand any file beyond what arrived in `codebase_scan.matched_files[].content` (read permission denied on the project tree, and the JSON payload truncated past `AdminController.java`). The findings below are anchored to what I could observe directly in `AdminController.java` plus the structural signals from the file list (no `src/test/**` entries surfaced, several `dto` siblings around the customer endpoint, an `AuditService`, a `PermissionFilter`, etc.). Anything I could not verify in source is called out explicitly so you can re-run with a wider scan if needed.

---

## HIGH priority

### H1. `GET /admin/customers` has no input validation and forwards raw user-supplied strings
`AdminController.getCustomers` accepts:
```java
@RequestParam String type,
@RequestParam String searchString,
@RequestParam(defaultValue = DEFAULT_PAGE_NUMBER) Integer pageNumber,
@RequestParam(defaultValue = DEFAULT_PAGE_SIZE)   Integer pageSize,
@RequestParam(defaultValue = DEFAULT_SORT_DIRECTION) String direction
```
There are no `@NotBlank`, `@Pattern`, `@Min/@Max`, or enum binding for `type` / `direction`, and no upper bound on `pageSize`. Risks:
- A caller can request `pageSize=1000000` and DoS the downstream `Yggdrasil` service / heap.
- `type` and `direction` are effectively free-form strings even though their domain is enumerable (e.g. `ASC`/`DESC`, a fixed customer-type set). Drift between front-end values and back-end expectations becomes a silent 200/empty rather than a 400.
- `searchString` is propagated straight into `adminService.getCustomers(...)`. Until that downstream call is reviewed, treat it as an injection sink (LDAP/SAP/SQL/URL — depends on the implementation; the package layout suggests a SAP backend, which is exactly the kind of place where unvalidated search terms have historically caused full-table scans or expression-language abuse).

**Fix:** bind `type`/`direction` to enums, add `@Min(0)` / `@Max(N)` on the page params, and `@Size`/`@Pattern` on `searchString`. Annotate the method with `@Validated`.

### H2. No visible automated tests for the customer endpoint
The 50-file scope returned by `codebase_scan` contains zero `src/test/**` paths. Either the test tree is genuinely absent for this feature, or it was filtered out of the scan — but even in the latter case there is no `@SpringBootTest` / `WebTestClient` reference inside the matched controller/service files. For a reactive endpoint that fans out to an external system, the absence of:
- a `WebTestClient` slice test for `/admin/customers`,
- a `StepVerifier`-based unit test on the `Mono<SearchCustomers.Response>` pipeline,
- and any contract test against the `Yggdrasil.SearchCustomers` schema,

is the single biggest maintainability risk. Reactive code regresses silently (operator order, `subscribeOn`, error mapping) and only manifests under load.

**Fix:** add at minimum a `@WebFluxTest(AdminController.class)` happy/sad path and a `StepVerifier` test on `AdminServiceImpl.getCustomers` with a mocked `WebClient`.

### H3. Authorization model for `/admin/customers` is implicit
The controller carries no `@PreAuthorize`, no `@Secured`, and no role check inline. Authorization appears to be delegated to `config/PermissionFilter.java` driven by `common/enums/Permission.java` and `SkipURLPermission.java`. That pattern is fine, but it means:
- there is no in-controller evidence that this endpoint requires a customer-admin permission;
- a future refactor that renames the path (`/admin/customers` → `/admin/v2/customers`) will silently bypass any URL-keyed permission map unless the filter is updated in lockstep;
- security review depends on reading three files instead of one.

**Fix:** add `@PreAuthorize("hasAuthority('...')")` (or your existing equivalent) directly on the handler as a defence-in-depth check, even if the filter remains the primary gate.

---

## MEDIUM priority

### M1. `@Loggable` on an endpoint that takes `searchString` — confirm masking
`Loggable` / `LoggableAspect` / `LogMasking` / `MaskingUtil` are all in the scan, which is good. But `searchString` for a customer lookup is often a phone number, BP number, NRIC/SSN-like ID, or email — PII that must be masked. The aspect needs to be verified for:
- masking arguments by parameter name *and* by content pattern, not just by type;
- not logging the full `Mono` response payload (which contains customer records).

If masking is only applied to known field names on response DTOs, raw `searchString` likely leaks into logs.

### M2. `direction` is a `String`, not `Sort.Direction`
Spring already ships a binder that gives you a 400 on bad input and removes the typo class of bug. Same for `type` if it has a finite domain.

### M3. Pagination contract is inconsistent with REST conventions
`pageNumber` + `pageSize` as separate `@RequestParam`s instead of accepting a `Pageable` means every call site re-derives offset math, and there is no central place to clamp `pageSize`. The defaults live as string constants (`DEFAULT_PAGE_NUMBER`, `DEFAULT_PAGE_SIZE`) — readable, but no enforced ceiling. See H1 fix.

### M4. Mixed web stacks in one controller
The imports pull in both `org.springframework.web.servlet.function.ServerResponse` *and* `reactor.core.publisher.Mono`. `ServerResponse` is Servlet-world; `Mono` is WebFlux-world. If the unused import is just dead code it's cosmetic, but if the app is genuinely running both stacks the threading model around `/admin/customers` is worth a closer look — blocking calls on a Reactor scheduler are a common footgun in this exact configuration.

### M5. Wildcard import in the controller
`import org.springframework.web.bind.annotation.*;` — minor, but it hides which annotations are actually in use and makes diffs noisier. The rest of the file uses explicit imports.

---

## LOW priority

### L1. Logging line `"AdminController :: searchCustomers :: Start"` duplicates the method name
With `@Loggable` already wrapping the call, a hand-rolled `log.info("...Start")` is redundant and will double-log. Either trust the aspect or drop the annotation, not both.

### L2. Method name vs. mapping path drift
Handler is named `getCustomers`, log message says `searchCustomers`, mapping is `/customers`. Pick one verb; "search" is the more accurate one given the `searchString` parameter.

### L3. DTO naming asymmetry
`GetCustomerResponse` (singular) sits next to a controller that only exposes a *list* search (`SearchCustomers.Response`). Either there is a missing `GET /admin/customers/{id}` handler that should also be in scope, or `GetCustomerResponse` is dead code. Worth confirming — a missing single-customer endpoint is a feature gap; an unused DTO is cleanup.

### L4. Audit trail not visible on the read path
`AuditService` / `AuditServiceImpl` / `AuditType` are in scope, but the controller does not invoke them. Reading customer data in an admin context is usually an auditable event under SOC2/GDPR. Confirm whether `@Loggable` already emits an audit record or whether this is a gap.

---

## What I could not verify (please re-scan or grant read access)

1. `AdminServiceImpl.getCustomers` — the actual downstream call. H1's severity depends on what happens to `searchString` there.
2. `PermissionFilter` + `Permission` enum — whether `/admin/customers` is actually gated and to which role.
3. `LoggableAspect` + `LogMasking` — whether `searchString` and the response body get masked.
4. Any `src/test/**` content — the scan returned none for this feature.
5. Rate limiting / WAF in front of `/admin/*` — not in the matched files.

If you can re-run the scan without truncation (or include `src/test/**` and `config/PermissionFilter.java` in full), I can convert the H1/H2/H3 items from "likely" to "confirmed" and tighten the remediation guidance.
