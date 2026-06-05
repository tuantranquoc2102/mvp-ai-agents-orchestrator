# Quality

_Agent: `reviewer` (Code Reviewer)_  
_Status: `success` · attempts: 1_

---

# Code Review — `/customer` Feature

**Note on inputs**: The `codebase_scan` payload was truncated mid-stream (only `AdminController.java` was visible in full; `AdminServiceImpl.java`, `GetCustomerResponse.java`, and `AdminServiceImplTest.java` were cut off). Read access to the workspace was denied, so this review is based on the visible controller plus inferences from file names and surrounding endpoints. **Findings flagged with ⚠ require the truncated files to confirm.**

## Scope

The `/customer` feature surfaces a single endpoint in `AdminController.java`:

```java
@Loggable
@GetMapping(value = "/customer")
public Mono<GetCustomerResponse> getCustomer(@RequestParam String bpNo, @RequestParam String userId) {
    log.info("AdminController :: getCustomerDetails :: Start");
    return adminService.getCustomer(bpNo, userId);
}
```

Backed by `AdminService.getCustomer(...)` → `AdminServiceImpl` → `GetCustomerResponse` DTO. One test file (`AdminServiceImplTest.java`) is present.

---

## HIGH severity

1. **No authorization on `/customer`** — the handler has no `@PreAuthorize`, `@Secured`, or equivalent. A `Permission` enum exists elsewhere in the scope (suggesting RBAC is established convention), so its absence here is a gap, not a stylistic choice. Combined with `bpNo` + `userId` as plain query params, this is a textbook **IDOR**: any caller who authenticates can request any other customer by guessing/iterating BP numbers. Verify whether a global filter or gateway enforces the check; if not, add explicit authorization and ownership validation (`bpNo` must belong to the caller, or the caller must hold an admin permission).

2. **PII in query string** — `userId` and `bpNo` ride in the URL, meaning they land in access logs, reverse-proxy logs, APM trace URLs, and browser/referrer history. The `@Loggable` aspect (see `LoggableAspect.java` in scope) likely captures method args too. Move to a `POST` with a body, or at minimum confirm the logging aspect redacts these fields.

3. **No input validation** — `bpNo` and `userId` are raw `String` with no `@NotBlank`, `@Pattern`, or length cap. Empty/oversized values pass straight to the service and downstream SAP/Yggdrasil calls. Add bean-validation constraints and `@Validated` on the controller.

## MEDIUM severity

4. **Inconsistent error handling across the controller** — `getBpNoByAccountNo` swallows *all* errors as `204 No Content` (`.onErrorResume(e -> ...noContent()...)`), which masks genuine 5xx faults as "no data." `getCustomer` does the opposite — no `.onErrorResume` at all, so errors bubble up raw. Pick one convention (preferably a global `@RestControllerAdvice`) and apply it uniformly.

5. **Mixed response shapes** — `Mono<GetCustomerResponse>`, `Mono<SearchCustomers.Response>`, `Mono<ResponseEntity<String>>`, `Mono<BaseResponse>` all coexist in one controller. Clients have to special-case each endpoint. Standardize on a single envelope (e.g. `BaseResponse<T>`).

6. **Test coverage signal is thin** ⚠ — only `AdminServiceImplTest.java` was matched for an `AdminService` exposing ~10 public methods. Cannot confirm depth without reading it, but verify `getCustomer` has at least: happy path, missing BP, mismatched `userId`/`bpNo` (the authorization case), and downstream-failure tests. No controller-layer test (`@WebFluxTest`) appears in scope.

7. **Log message lies about method name** — the log line says `getCustomerDetails`, the method is `getCustomer`. Minor, but it breaks log-grep workflows. Also: start-log without a corresponding end-log or correlation ID hurts production debugging.

## LOW severity

8. **DTO nesting inconsistency** — sibling endpoints use nested request/response classes (`UpdateBpNo.Request`, `Subscription.Update.Response`, `Yggdrasil.SearchCustomers.Response`), but `GetCustomerResponse` is top-level. Aligning the style would aid discoverability.

9. **`Mono<GetCustomerResponse>` with no explicit `.switchIfEmpty`** ⚠ — without seeing the service, the controller has no defensive handling for "customer not found." Empty `Mono` from WebFlux becomes a `200 OK` with empty body unless explicitly mapped to `404`.

10. **Wildcard import** — `import org.springframework.web.bind.annotation.*;` is in the controller. Most teams' style guides forbid wildcards for clarity.

---

## Suggested follow-ups before merge

- Confirm authorization story (filter chain vs. method-level) and add `@PreAuthorize` if no gateway-level check exists.
- Re-run review with read access so `AdminServiceImpl.getCustomer`, `GetCustomerResponse`, and the test class can be verified — findings 1, 6, and 9 hinge on those files.
- Decide on a global error-handling strategy and remove the per-endpoint `onErrorResume` hacks.
