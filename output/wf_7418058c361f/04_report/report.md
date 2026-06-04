# Report

_Agent: `assistant` (General Assistant)_  
_Status: `success` · attempts: 1_

---

# Final Analysis Report — `GET /v4/charts/{premises_id}`

## Overview

The feature exposes a single chart-retrieval endpoint for a given premises identifier in the `jarvis-api` Go service. Within the pre-filtered scope, the feature surfaces in exactly one file — `internal/app/v4/routes.go` (line 68) — which is the v4 API route-composition module built on `go-chi/chi/v5`. The handler logic itself (`usage.Charts`, in `internal/app/v4/usage`) is out of scope for this scan, so all findings below describe the **routing, authentication, and middleware composition** surrounding the feature, not its business logic.

The salient fact is that the same handler is reachable through **three distinct entry points**, reflecting an in-flight migration from a legacy direct Auth0 path to a Mulesoft B2C gateway, plus a parallel machine-to-machine (M2M) channel:

| Entry point | Path | Caller | Identity resolution |
|---|---|---|---|
| Legacy authenticated group | `GET /v4/charts/{premises_id}` | End-user (Auth0 ID token) | `authc.Middleware` + `bp.DetailsByJWTMiddleware()` |
| Mulesoft gateway | `GET /v4/charts/{premises_id}` | End-user via B2C gateway | Gateway JWT claims + `ScopeUtilities` / `ScopeRBAC` / `ScopeInfinity` |
| Internal M2M | `GET /v4/user/charts/{premises_id}` | Service-to-service | `basiciam.RequireClaimScope(ScopeM2MReadChart)` + `AudM2M` + `bp.DetailsByFormMiddleware()` |

## Architecture

**Composition layering (as observed in `internal/app/v4/routes.go`):**

1. **Transport** — chi router; `handler.Wrap` (from `internal/pkg/handler`) adapts feature handlers to the HTTP signature.
2. **Cross-cutting middleware** — `downtime.Middleware` (maintenance gate), `middleware.LimitPayload(5MB)` (payload cap).
3. **Authentication / authorization** — three variants per the table above; the legacy `authc` group is explicitly commented as slated for removal once Mulesoft migration completes.
4. **Context enrichment** — `bp.DetailsByJWTMiddleware()` for user-facing routes vs. `bp.DetailsByFormMiddleware()` for M2M, meaning the BP/premises context is resolved from a JWT subject in one case and from form data in the other.
5. **Feature handler** — `usage.Charts` in `internal/app/v4/usage` (not in scan).

**Notable design properties for this feature:**

- **Single-handler, multi-front-door** pattern: `usage.Charts` is reused unchanged across all three mounts. The URL contract for `{premises_id}` is uniform (a chi path parameter), so the handler reads it the same way regardless of caller. Only the *identity* of the caller — and thus how `bp` resolves premises ownership — differs by mount.
- **Path divergence on the M2M side**: the internal route is mounted under `/v4/user`, yielding the externally distinct path `/v4/user/charts/{premises_id}`. This keeps the M2M surface namespaced even though the handler is shared.
- **Authorization is enforced *outside* the handler**, in middleware (scope/audience checks for M2M, scope checks for the gateway path, generic Auth0 validation for the legacy path). The handler is presumed to trust the enriched BP context.
- **No build/config files** (`main.go`, `go.mod`, Dockerfile, CI manifests) appear in the feature-scoped slice, so the bootstrap that wires `v4.Router(...)`, `v4.GatewayAuthenticatedRoutes(...)`, and `v4.GatewayPublicRoutes(...)` is out of view; the file is a subordinate composition module, not an entry point.

## Quality & Risk

**Strengths**

- **Clean separation of concerns** between routing, middleware, and handler — the feature itself is a one-line registration, which is the right size for this layer.
- **Migration intent is explicit**: the deprecation comment on the legacy `authenticated` group makes the transition state legible to future maintainers.
- **Distinct scopes per channel** (`ScopeM2MReadChart` vs. user scopes) provide a credible least-privilege boundary between M2M and end-user callers.

**Risks and smells**

1. **Triple exposure of the same handler is a sustained authorization-surface risk.** Any change to `usage.Charts`'s assumptions about caller identity must hold simultaneously across three middleware stacks. If the handler ever reads anything beyond `{premises_id}` and the `bp` context (e.g., a JWT claim directly), behavior will diverge silently between the legacy, gateway, and M2M paths.
2. **Two different BP-resolution strategies** (`DetailsByJWTMiddleware` vs. `DetailsByFormMiddleware`) feed the same handler. The form-driven path is materially weaker — it relies on the caller to assert the IAM_ID and trusts an M2M scope to gate it. Worth confirming there is no path where form input could reach the JWT-mount or vice versa.
3. **Path collision between legacy and gateway mounts**: both register `GET /v4/charts/{premises_id}` at the same URL. Routing precedence depends on the order in which the parent router mounts `authenticatedRoutes` vs. `GatewayAuthenticatedRoutes`. If both are mounted on the same chi tree, one will shadow the other; if they are mounted on different sub-routers (e.g., behind different host/prefix selectors at the bootstrap level outside this file), the contract is fine — but that invariant is invisible from this file alone.
4. **Deprecation debt**: the legacy `authc` path is committed-as-deprecated but still live. Until it is removed, every fix or security patch to the chart endpoint must be validated against the legacy auth pipeline as well.
5. **Test coverage unverifiable from this slice.** No test files for `usage.Charts` or for the route registration appear in the pre-filtered scan, so coverage for the multi-mount behavior cannot be asserted.
6. **5MB payload limit on a `GET`** is harmless but suggests the limit is applied at a group level rather than per-method — worth confirming it is not masking a misuse elsewhere.

## Recommended Next Steps

1. **Bring `internal/app/v4/usage/charts*.go` (and its tests) into scope** and re-run analysis. The single biggest blind spot is the handler itself: until we see how it consumes `{premises_id}` and the `bp` context, the authorization claims above are inferential.
2. **Audit route precedence at the bootstrap.** Inspect wherever `v4.Router`, `v4.GatewayAuthenticatedRoutes`, and `v4.GatewayPublicRoutes` are mounted to confirm the two `GET /v4/charts/{premises_id}` registrations cannot collide on the same chi tree. Document the invariant.
3. **Add (or surface) integration tests per entry point** — one each for legacy auth, gateway auth, and M2M — that assert: (a) authorization rejection on missing scope/audience, (b) `premises_id` ownership enforcement, and (c) identical response shape across the three mounts. This protects the single-handler/multi-front-door property during the Mulesoft migration.
4. **Sunset the legacy `authc` mount on a dated milestone.** Convert the inline comment into a tracked ticket with an owner and a removal date tied to the Mulesoft cut-over. The longer both mounts coexist, the higher the chance they drift in middleware composition.
5. **Tighten the M2M form-based BP resolution.** Verify that `bp.DetailsByFormMiddleware()` validates the asserted IAM_ID against the M2M client's allowed premises, not just the presence of `ScopeM2MReadChart`. If not, a single M2M credential can read charts for any premises.
6. **Make the scope model explicit in code or docs.** Today the gateway path checks `ScopeUtilities`/`ScopeRBAC`/`ScopeInfinity` while the M2M path checks `ScopeM2MReadChart`. A short comment block above the registration explaining *why each scope set is sufficient for chart read* would help future reviewers avoid weakening it accidentally.
7. **Confirm payload-limit and downtime middleware apply uniformly** across all three mounts; if any path bypasses `downtime.Middleware`, the maintenance gate is incomplete.
