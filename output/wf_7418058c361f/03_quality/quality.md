# Quality

_Agent: `reviewer` (Code Reviewer)_  
_Status: `success` · attempts: 1_

---

# Code Review — `/v4/charts/{premises_id}`

Scope is narrow: routing is in `internal/app/v4/routes.go:68` (and a related M2M handler at `/v4/user/charts/{premises_id}`). I was not granted read access to the `usage.Charts` handler or its tests, so this review is bounded to the routing/middleware contract and what it implies about the feature.

## Findings

### HIGH — Endpoint exposed via two parallel auth paths, one explicitly deprecated
`/v4/charts/{premises_id}` is registered in `authenticatedRoutes`, which is mounted by **both**:
- `authenticated()` — direct Auth0 JWT (`authc.Middleware`), explicitly tagged `// Deprecated: the function will be removed 3 months after moving behind mulesoft`
- `GatewayAuthenticatedRoutes()` — Mulesoft-fronted path

The deprecation comment has no date and no kill-switch. Until removed, the chart endpoint is reachable by two distinct authentication flows with different scope/audience checks, doubling the attack surface and complicating audit logging. **Recommendation:** add an explicit sunset date, a feature flag to disable the direct path in non-dev environments, and confirm whether mobile/web clients have actually migrated.

### HIGH — No evidence of authorization on `{premises_id}` at the routing layer (IDOR risk)
The middleware chain for the route is:
1. `downtime.Middleware()`
2. `LimitPayload(5MB)`
3. `authc.Middleware{Scope:true, IDToken:true}` (or Mulesoft equivalent)
4. `bp.DetailsByJWTMiddleware()` — resolves the *caller's* BP details from the JWT
5. `handler.Wrap(usage.Charts)`

Nothing in this chain verifies that `{premises_id}` belongs to the authenticated business partner. The handler `usage.Charts` *must* enforce this ownership check; if it does not, any authenticated user can read any premises' chart data. **Recommendation:** verify there is an explicit premises↔BP authorization check inside `usage.Charts` (and a test covering "caller requests another user's premises_id → 403"). This should be the top item to confirm.

### MEDIUM — No per-route rate limiting or response caching middleware
Chart endpoints typically execute expensive time-series aggregations. The only protective middleware is `LimitPayload` (request-size, irrelevant for GET) and global `downtime`. There is no:
- Per-user / per-premises rate limit
- Response cache or `Cache-Control` enforcement
- Timeout middleware (relies entirely on handler/transport)

An authenticated client can drive arbitrary load by varying `premises_id` or query params. **Recommendation:** add a rate-limit middleware on the BP-details group, or at minimum on this route.

### MEDIUM — Inconsistent parameter sourcing for the M2M sibling
The M2M variant `/v4/user/charts/{premises_id}` uses `bp.DetailsByFormMiddleware()` — i.e., reads `IAM_ID` from form data on a `GET` request. GET + form-encoded body is non-standard (some proxies/CDNs strip bodies on GET) and tooling will not document it in OpenAPI cleanly. Flag for consistency: prefer query string, or change the verb. Also confirm `ScopeM2MReadChart` is enforced *before* the BP middleware, which it is here — good.

### MEDIUM — Same handler bound to two different URL shapes
`usage.Charts` is registered at both:
- `/v4/charts/{premises_id}` (end-user JWT path)
- `/v4/user/charts/{premises_id}` (M2M path)

If the handler branches on auth context to change behavior (e.g., bypassing the ownership check for M2M callers), that conditional logic is invisible from the router and easy to break. **Recommendation:** if the handler has dual-mode logic, split into two thin handlers with shared business logic; the router should make the contract obvious.

### LOW — Test coverage signal
The scan returned only `routes.go` (1 file, 5.5KB) for the feature query. No `*_test.go` co-located with the route registration. Confirm:
- Router test exercises the route is mounted under both `authenticated` and `GatewayAuthenticatedRoutes` (and only those).
- Handler test exists for `usage.Charts` covering: happy path, missing premises, wrong-owner premises, downstream timeout, invalid `premises_id` format.

### LOW — Magic constant for payload size
`middleware.LimitPayload(5 << (10 * 2)) //5MB` is correct but cryptic. Extract `const MaxPayloadBytes = 5 * 1024 * 1024` (or use a typed `5 * datasize.MB` helper) so the limit is greppable and consistent across routers — the same expression is repeated for `GatewayAuthenticatedRoutes`.

### LOW — Opaque `handler.Wrap`
`handler.Wrap(usage.Charts)` hides the error/response contract. Not a defect; just note that any review of HTTP status codes, panic recovery, and structured-logging guarantees has to happen inside `internal/pkg/handler`, not here.

## Prioritized action list
1. **Confirm ownership check inside `usage.Charts`** (HIGH — IDOR).
2. **Date the deprecation and gate the direct-auth path behind config** (HIGH).
3. **Add rate-limit + request-timeout middleware to the BP-details group** (MEDIUM).
4. **Verify/split the handler if it dual-modes M2M vs end-user** (MEDIUM).
5. **Reconsider form-data IAM_ID on a GET** for the M2M sibling (MEDIUM).
6. **Add router + handler tests covering both mount points** (LOW).
7. **Extract the 5MB literal into a named constant** (LOW).

Items #1 and #4 cannot be fully assessed without reading `internal/app/v4/usage/` and `internal/app/v3/bp/`; recommend the next reviewer fetch those before sign-off.
