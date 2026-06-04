# Inventory

_Agent: `researcher` (Research Specialist)_  
_Status: `success` · attempts: 1_

---

# Codebase Inventory Summary — Feature `/v4/charts/{premises_id}`

## Scope of Pre-Filtered Inventory
The feature-scoped scan returned a single matching file out of the broader `jarvis-api` repository:

| Metric | Value |
|---|---|
| Feature query | `/v4/charts/{premises_id}` |
| Matched files | 1 |
| Total bytes | 5,499 |
| Dominant language | **Go** (100%) |
| Match location | `internal/app/v4/routes.go` (line 68) |

## Notable File

### `internal/app/v4/routes.go`
The sole file referencing the feature. It is the **v4 API route registration module** for the `jarvis-api` service — a Go package using the `go-chi/chi/v5` router. It is not an entry point itself but is the routing composition layer wired into the application's HTTP server.

## Feature-Specific Findings

The endpoint `/v4/charts/{premises_id}` is **registered twice** in this file under different router groups:

1. **External / authenticated route (line 68)** — inside `authenticatedRoutes(r)`:
   ```go
   r.Get("/v4/charts/{premises_id}", handler.Wrap(usage.Charts))
   ```
   - Wrapped by the `bp.DetailsByJWTMiddleware()` group (requires BP details from JWT).
   - Reached via two paths:
     - Legacy `authenticated` group → `authc.Middleware` (deprecated, slated for removal post-Mulesoft migration).
     - `GatewayAuthenticatedRoutes` → behind Mulesoft B2C gateway with scope checks (`ScopeUtilities`/`ScopeRBAC` + `ScopeInfinity`).

2. **Internal / M2M route** — inside `internal(r)` under `r.Route("/v4/user", ...)`:
   ```go
   r.With(basiciam.RequireClaimScope(auth0.ScopeM2MReadChart)).
       Get("/charts/{premises_id}", handler.Wrap(usage.Charts))
   ```
   - Full path: `/v4/user/charts/{premises_id}`.
   - OAuth2 machine-to-machine; requires `ScopeM2MReadChart` and `AudM2M` audience.
   - Uses `bp.DetailsByFormMiddleware()` to resolve IAM_ID from form data instead of JWT.

## Handler & Dependency Surface

- **Handler implementation**: `usage.Charts` — imported from `internal/app/v4/usage` (handler body not in this pre-filtered scope).
- **Handler wrapper**: `handler.Wrap` from `internal/pkg/handler`.
- **Auth packages**: `internal/app/v3/authc`, `internal/pkg/auth0`, `code.in.spdigital.sg/sp-digital/infinity/pkg/basiciam`.
- **Context enrichment**: `internal/app/v3/bp` (BP/premises details middleware, both JWT- and form-based variants).
- **Cross-cutting middleware**: `downtime.Middleware`, `middleware.LimitPayload(5MB)`.

## Likely Entry Points & Build/Config Files

Within the feature-scoped slice, no `main.go`, `go.mod`, Dockerfile, or CI/build manifest is present. The matched file is a **subordinate routing module**; the application bootstrap that calls `v4.Router(...)`, `v4.GatewayAuthenticatedRoutes(...)`, and `v4.GatewayPublicRoutes(...)` lives outside this filtered set (the truncation also indicates a `GatewayPublicRoutes` function continues beyond what was shown).

## Architectural Observations Relevant to the Feature

- **Triple-exposure model**: the same `usage.Charts` handler is served via (a) legacy direct auth, (b) Mulesoft gateway auth, and (c) internal M2M — a deliberate transition pattern as legacy auth is being retired.
- **Deprecation signal**: comments explicitly mark the `authenticated` group for removal once Mulesoft migration completes; the feature's external entry point will consolidate onto `GatewayAuthenticatedRoutes`.
- **Path-parameter contract**: `{premises_id}` is a chi URL parameter; identical handler reuse between external and internal routes implies the handler reads `premises_id` from the URL uniformly, while caller identity (BP details) is resolved differently per group.
