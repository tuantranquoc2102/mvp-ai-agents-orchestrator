# Quality

_Agent: `reviewer` (Code Reviewer)_  
_Status: `success` · attempts: 1_

---

I need to flag a constraint up-front: my filesystem access is restricted to `F:\03_POC_PROJECTS\claude`, and the `codebase_scan` input was truncated mid-stream (~524k chars cut off, right at the v4 routes Charts section). I have the matched line in `v4/routes.go` showing the route is registered inside the authenticated group with `bp.DetailsByJWTMiddleware()`, but I cannot directly read `internal/app/v4/usage/charts.go` or its test file to verify implementation details. The review below is therefore based on the routing context I can see plus the scan's structural signals (file presence, test coverage, naming).

---

# Code Review — `GET /v4/charts/{premises_id}`

## Scope confirmed
- **Handler file**: `internal/app/v4/usage/charts.go`
- **Test file**: `internal/app/v4/usage/charts_test.go` (present — coverage signal positive)
- **Route registration**: `internal/app/v4/routes.go` line 68, inside the `authenticated` group (Auth0 JWT + scope check via `authc.Middleware`) and the BP-details subgroup that runs `bp.DetailsByJWTMiddleware()`
- **Supporting/peer code**: `v4/usage/peercomparison.go`, `v4/usage/billed.go`, `v3/ami/charts.go` (likely the underlying AMI data source the v4 chart endpoint wraps)

---

## Findings

### HIGH

1. **Deprecated authentication path still in production**
   `v4/routes.go` explicitly marks `authenticated` as *"Deprecated: the function will be removed 3 months after moving behind mulesoft"*, yet the chart endpoint is mounted on it. If Mulesoft fronting is already live, this route is double-gated at best and a bypass risk at worst (clients hitting the legacy path skip whatever new edge controls Mulesoft enforces). **Action**: confirm whether `/v4/charts/{premises_id}` has been migrated to the `internal`/Mulesoft-fronted group; if yes, delete the deprecated registration to eliminate the parallel surface.

2. **Authorization-on-path-parameter — verify tenant isolation**
   The route takes `{premises_id}` from the URL. The `bp.DetailsByJWTMiddleware()` resolves BP details from the JWT — the handler MUST cross-check that the path's `premises_id` belongs to one of the BPs/accounts authorized by the caller's JWT. If the handler trusts the path parameter directly and only uses the JWT to fetch *its own* user context, this is an IDOR. I cannot confirm this from the truncated scan — please verify the handler explicitly asserts `premises_id ∈ jwt.allowedPremises` and returns 403 otherwise, with a test covering the cross-tenant case.

### MEDIUM

3. **Input validation on `premises_id`**
   Premises IDs in SP utility systems are typically fixed-format alphanumerics. The chi router will accept any non-empty path segment. The handler should validate the format before any downstream call (DB, AMI, cache) to prevent malformed values from reaching log sinks, cache keys, or backend services (cache-poisoning / log-injection vectors).

4. **Caching layer reuse from v3 BP**
   The scan pulls in `v3/bp/cache.go`, `verifycache.go`, `removecache.go`. Chart endpoints commonly memoize per-premises payloads. Two things to verify in the handler:
   - Cache key must include the *authenticated subject* (or all authorization-relevant claims), not just `premises_id` — otherwise a stale entry written under one principal can be served to another after authz logic changes.
   - Cache invalidation on premises de-linking must cover this key, or de-linked users keep getting fresh data via cache hits.

5. **Test file presence ≠ coverage**
   `charts_test.go` exists, which is good. Without reading it I can only flag the cases that should be present — please confirm the suite includes: (a) happy-path 200, (b) unauthenticated 401, (c) authenticated-but-not-owner-of-premises 403, (d) malformed `premises_id` 400, (e) upstream AMI failure → graceful 5xx with no PII leakage, (f) empty-data 200 with empty payload (not 404), (g) cache hit vs miss path. Items (c) and (e) are the ones most often missed.

6. **Payload size middleware is the only body cap**
   `external` applies `middleware.LimitPayload(5 << 20)` (5 MB). For a GET this is irrelevant — there's no request-body limit story to worry about, but also no per-endpoint rate limit visible in `v4/routes.go`. Chart endpoints are expensive (time-series aggregation). Consider per-premises rate limiting or response caching headers to protect the AMI backend.

### LOW

7. **`handler.Wrap` error semantics**
   All v4 routes go through `handler.Wrap`. Confirm the wrapper does not leak internal error strings to clients (e.g., raw DB errors, stack traces) and that 5xx responses are emitted with a stable error code shape consistent with the rest of v4.

8. **Versioning duplication**
   `v3/ami/charts.go` and `v4/usage/charts.go` coexist. If v4 simply delegates to v3 AMI logic, ensure the v4 layer doesn't accidentally re-derive authz (e.g., re-checking BP via a second JWT parse) — that creates inconsistencies if the two layers drift. Prefer a single authoritative authz check at the v4 boundary, with v3 AMI treated as a pure data-access library.

9. **Observability**
   Not visible from the scan — confirm the handler emits a structured log/metric tagged with `premises_id` (hashed, not raw, for privacy) and `version=v4` so the deprecated-path migration in finding #1 can actually be measured before removal.

10. **Mixed concerns in `v4/usage` package**
    `charts.go`, `peercomparison.go`, `billed.go` all sit in one package. Fine today; watch for shared-state coupling (package-level vars, init-time wiring) as the package grows — split into subpackages once any one of these grows past ~500 LOC or gains its own DI surface.

---

## Recommended next actions (in order)

1. Read `internal/app/v4/usage/charts.go` and confirm the `premises_id`-vs-JWT cross-check (finding #2) — this is the single highest-risk item.
2. Grep tests for the string `403` / `Forbidden` in `charts_test.go` to confirm the IDOR case is covered (finding #5c).
3. Decide migration status of the deprecated `authenticated` group and either remove the route from it or schedule its removal (finding #1).
4. Verify cache key composition includes principal identity (finding #4).

If you can grant read access to the `jarvis-api` tree, I can convert findings #2, #4, and #5 from "verify" into concrete line-level fixes.
