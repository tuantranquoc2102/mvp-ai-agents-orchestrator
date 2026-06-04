# Architecture

_Agent: `architect` (Software Architect)_  
_Status: `success` · attempts: 1_

---

# Architecture Analysis — `/v4/charts/{premises_id}`

## Scope

Only one file in the scan references this feature: `internal/app/v4/routes.go`. The handler implementation (`usage.Charts`) lives in `internal/app/v4/usage` but was not included in the scan, so this analysis is restricted to the **routing / composition layer** for this endpoint.

## Endpoint Registration

The route `/v4/charts/{premises_id}` is registered **twice** with the same handler `usage.Charts`, but under different access paths:

| Mount point | Path | Audience | Auth model |
|---|---|---|---|
| `authenticatedRoutes` (external + gateway) | `GET /v4/charts/{premises_id}` | End-user clients (Auth0 ID token, or Mulesoft gateway) | `authc.Middleware` *or* Mulesoft `JWTClaimsSecurityContextMiddleware` + scope checks |
| `internal` | `GET /v4/user/charts/{premises_id}` | Machine-to-machine | `basiciam.RequireAccessToken` + `RequireClaimAudience(AudM2M)` + `RequireClaimScope(ScopeM2MReadChart)` |

Same handler, three effective entry-points (legacy direct, Mulesoft gateway, M2M).

## Layering & Modules

```
internal/app/v4/routes.go            <-- routing/composition (this file)
  └── usage.Charts                   <-- feature handler (internal/app/v4/usage)
        wrapped by handler.Wrap      <-- transport adapter (internal/pkg/handler)

Cross-cutting middleware:
  - v3/authc           Auth0 ID-token / scope verification (legacy path)
  - v3/bp              "BP details" enrichment (JWT- or form-driven)
  - v3/downtime        Maintenance/feature-flag gate
  - pkg/auth0          Auth0 JWKS + scope constants
  - basiciam (infinity)Generic IAM primitives for M2M
  - web.v2/middleware  Payload size limit
  - go-chi/chi/v5      HTTP router
```

Logical layers for this feature:

1. **Transport** — chi router + `handler.Wrap` adapter.
2. **Cross-cutting middleware** — downtime gate, payload limit, authn/authz, BP enrichment.
3. **Feature handler** — `usage.Charts` (not in scan).

Communication is purely in-process function composition via chi middleware; no event bus or RPC at this layer.

## Middleware Chain for `/v4/charts/{premises_id}`

**External (legacy / direct):**
```
downtime → LimitPayload(5MB) → authc.Middleware(Scope+IDToken) → bp.DetailsByJWTMiddleware → usage.Charts
```

**Gateway (Mulesoft b2c):**
```
downtime → LimitPayload(5MB) → JWTClaimsSecurityContextMiddleware
  → MulesoftRequireScopesOrMatcher(Utilities|RBAC) → MulesoftRequireScope(Infinity)
  → bp.DetailsByJWTMiddleware → usage.Charts
```

**Internal M2M (`/v4/user/charts/{premises_id}`):**
```
RequireAccessToken(JWKS) → RequireClaimAudience(AudM2M)
  → bp.DetailsByFormMiddleware → RequireClaimScope(ScopeM2MReadChart) → usage.Charts
```

The BP-details source differs by audience: JWT-derived for end users, form-derived for M2M. This is the key abstraction that keeps `usage.Charts` agnostic of caller identity.

## External Dependencies (observed)

- `code.in.spdigital.sg/sp-digital/golang/web.v2/middleware` — payload limiter.
- `code.in.spdigital.sg/sp-digital/infinity/pkg/basiciam` — IAM primitives (access token, audience, scope).
- `github.com/go-chi/chi/v5` — HTTP router.
- Internal `pkg/auth0`, `pkg/handler` — Auth0 constants/JWKS and handler-wrap helper.

No DB, cache, or downstream-service dependency is visible at this layer — those will live inside `usage.Charts`.

## Structural Smells

1. **Cross-version coupling.** A v4 routes file imports v3 packages (`v3/authc`, `v3/bp`, `v3/downtime`). The route comment `Deprecated: the function will be removed 3 months after moving behind mulesoft` confirms this is intentional bridging, but it makes v4 non-self-contained and complicates eventual v3 retirement. The `authenticated` group is explicitly deprecated yet still wired in.

2. **Duplicate registration of the same handler with different auth contracts.** `usage.Charts` is mounted at both `/v4/charts/{premises_id}` (end-user) and `/v4/user/charts/{premises_id}` (M2M). Any change to its request/response contract must be validated against two scope models. There is no shared sub-router or contract layer enforcing this — they are independent `r.Get(...)` calls. Risk: silent divergence (e.g. M2M path forgetting a new middleware added to the end-user path, as happens today with `downtime` and `LimitPayload`, which the `internal` group does **not** apply).

3. **`authenticatedRoutes` reused verbatim by `GatewayAuthenticatedRoutes`.** Convenient for migration, but it means the end-user chart endpoint inherits whatever the legacy `authenticated` group needed. When the legacy path is removed, the gateway path will silently keep working — fine — but the function name `authenticatedRoutes` will be misleading (it will be gateway-only). Plan to rename at cutover.

4. **Scope check placed *after* BP enrichment on the M2M path.** `bp.DetailsByFormMiddleware` runs before `RequireClaimScope(ScopeM2MReadChart)` inside the `/v4/user` route. A caller missing the chart scope still pays the BP-lookup cost (and any side effects). Move scope checks to the top of the chain.

5. **5 MB payload limit on a `GET` chart endpoint.** Harmless but inappropriate — `LimitPayload` adds no value on `GET`. Worth noting only because it is applied through the shared external middleware stack; not an issue specific to this feature.

6. **No router-level `Route("/v4/charts", …)` grouping.** Other v4 features (`smrd`, `user`, `accounts`, `byob`) use `r.Route(...)` sub-trees; charts is a single line at the top level. Minor inconsistency, not a defect.

## What's Not Visible (gaps in the scan)

- `usage.Charts` handler — request validation, query parameters, response shape, downstream calls (DB / SMRD / partner services), caching strategy.
- `bp.DetailsByJWTMiddleware` / `bp.DetailsByFormMiddleware` — what "BP details" actually attaches to the context and whether `usage.Charts` reads it.
- `handler.Wrap` — error mapping and response encoding contract.
- The truncated tail of `routes.go` (GatewayPublicRoutes onward).

A follow-up scan that expands to `internal/app/v4/usage/**`, `internal/app/v3/bp/**`, and `internal/pkg/handler/**` would be needed to assess the feature's data flow and dependency graph end-to-end.
