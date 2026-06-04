# Report

_Agent: `assistant` (General Assistant)_  
_Status: `success` · attempts: 1_

---

# Final Analysis Report — Feature `/v4/charts/{premises_id}`

## Overview

The `/v4/charts/{premises_id}` endpoint is a versioned chart/usage-data feature served by the `jarvis-api` Go service. It is registered in `internal/app/v4/routes.go` (line 68) and implemented by the `usage.Charts` handler in `internal/app/v4/usage/charts.go`, with test coverage in `internal/app/v4/usage/charts_test.go`. The feature scope, as filtered, comprises 30 Go files (~274 KB) entirely under `internal/app/`.

The endpoint is **dual-mounted**:
- **External path**: `GET /v4/charts/{premises_id}` for end-user JWT-authenticated consumers, with the middleware chain `downtime.Middleware` → `LimitPayload(5MB)` → `authc.Middleware{Scope, IDToken}` → `bp.DetailsByJWTMiddleware`.
- **Internal/M2M path**: `GET /v4/user/charts/{premises_id}`, gated by `basiciam.RequireAccessToken(auth0.JWKSKeyFunc)`, `basiciam.RequireClaimAudience(auth0.AudM2M)`, `basiciam.RequireClaimScope(auth0.ScopeM2MReadChart)`, and `bp.DetailsByFormMiddleware`.

A v3 ancestor exists at `internal/app/v3/ami/charts.go` (+ `charts_test.go`), confirming a deliberate version-evolution pattern (`v1`–`v5` packages, with v4 being the active implementation for this feature).

## Architecture

The feature follows a clean layered design built on `go-chi/v5` and the in-house `code.in.spdigital.sg/sp-digital/golang/web.v2` framework:

1. **Routing layer** — `internal/app/v4/routes.go` splits traffic into `external` (downtime gate + 5 MB payload limit + JWT) and `internal` (M2M OAuth2 with audience + scope claims) groups before further splitting external into `authenticated` and `public` subtrees.

2. **Authentication & context enrichment** — Cross-cutting concerns are imported from `internal/app/v3`:
   - `authc.Middleware` validates JWT scope + ID token on the external path.
   - `bp.DetailsByJWTMiddleware` (external) and `bp.DetailsByFormMiddleware` (internal) load Business Partner / premises context into the request `context.Context`, backed by caching in `internal/app/v3/bp/cache.go` and accessors in `bp/context.go`.
   - `basiciam` + `auth0` packages (`internal/pkg/auth0`) provide the JWKS key function and M2M scope/audience constants (`ScopeM2MReadChart`, `AudM2M`).

3. **Handler adapter** — `internal/pkg/handler.Wrap` bridges the typed `usage.Charts` business handler to a `chi.Handler`, presumably standardizing error→HTTP translation and request decoding.

4. **Feature handler** — `internal/app/v4/usage/charts.go` is the single handler reused unchanged for both mount points. Sibling files `peercomparison.go` and `billed.go` indicate `usage` is the "consumption analytics" bounded context and likely share helpers/types with `charts.go`.

5. **Domain/data access (inferred)** — The handler almost certainly delegates downstream to AMI/billing services; the v3 ancestor `internal/app/v3/ami/charts.go` suggests a historical link to an AMI (Advanced Metering Infrastructure) integration that may have been refactored or kept as a dependency.

**Key architectural strength**: Auth mode differs per mount point, but business logic is shared via a single handler — a sound DRY pattern. **Key tension**: v4 reaches back into v3 (`v3/authc`, `v3/bp`, `v3/downtime`) for middleware, which couples versions and may complicate future deprecation of v3.

## Quality & Risk

**Strengths**
- **Test coverage at both versions**: `internal/app/v4/usage/charts_test.go` and `internal/app/v3/ami/charts_test.go` exist, indicating regression protection across the migration.
- **Defense-in-depth middleware**: 5 MB payload cap, downtime gating, explicit JWT validation, separate M2M scope (`ScopeM2MReadChart`) — the security envelope around the endpoint is well-defined.
- **Context-based parameter passing**: BP details flow via `context.Context` (per `bp/context.go`), avoiding scattered URL/header parsing inside the handler.

**Risks**
1. **Cross-version coupling**: `v4/routes.go` depends on `v3/authc`, `v3/bp`, and `v3/downtime`. If v3 is ever retired or refactored, this feature breaks silently unless the middleware is promoted to a shared `internal/pkg` location.
2. **Authorization parity between mount points**: The external path requires only JWT scope + ID token; the M2M path additionally checks `ScopeM2MReadChart`. There is no obvious external-side scope check for the chart resource itself — worth confirming that JWT scope validation in `authc.Middleware{Scope, IDToken}` actually constrains chart access and isn't just an authentication check.
3. **BP cache correctness** (`internal/app/v3/bp/cache.go`): Caching BP/premises details is a common source of cross-tenant data leakage if the cache key doesn't fully encode the requesting identity. This warrants explicit verification given the multi-tenant `premises_id` shape of the URL.
4. **Path-param vs. context mismatch**: The route declares `{premises_id}` as a URL parameter, but middleware also injects premises/account into context. If the handler trusts the URL param without cross-checking against the BP-context-derived premises, it could allow IDOR (one authenticated user reading another premises). This is the single highest-priority item to confirm in `usage/charts.go`.
5. **5 MB payload limit on a GET endpoint** is generous; not a vulnerability per se, but inconsistent with typical read endpoints and may be a copy-paste artifact from the broader route group.
6. **Observability gap** (inferred): No tracing/metrics middleware appears in the chain shown. If absent, latency regressions on chart queries will be hard to diagnose.

## Recommended Next Steps

1. **Audit IDOR risk in `internal/app/v4/usage/charts.go`** — Verify that the handler reconciles the `{premises_id}` URL parameter against the premises loaded into context by `bp.DetailsByJWTMiddleware`. Reject requests where they disagree. This is the highest-leverage check.
2. **Verify BP cache keying in `internal/app/v3/bp/cache.go`** — Confirm cache keys include the caller identity (JWT subject or BP id) so concurrent multi-tenant requests cannot collide.
3. **Document and confirm scope semantics on the external path** — Inspect `internal/app/v3/authc/middleware.go` to confirm what `Scope` actually enforces for `/v4/charts/...`; add an explicit `ScopeReadChart` (mirroring the M2M side) if missing.
4. **Plan promotion of shared middleware out of `v3/`** — Move `authc`, `bp`, and `downtime` to `internal/pkg/` (or a `internal/middleware/`) so future v3 deprecation does not strand v4. Update imports in `internal/app/v4/routes.go` accordingly.
5. **Compare v3 → v4 handler diff** — Run a side-by-side review of `internal/app/v3/ami/charts.go` vs. `internal/app/v4/usage/charts.go` to confirm v4 is a strict superset (no silently dropped validation, no behavioral regressions on edge cases that v3 tests cover but v4 doesn't).
6. **Confirm test depth in `internal/app/v4/usage/charts_test.go`** — Specifically that it covers: (a) mismatched URL `premises_id` vs. JWT-derived premises, (b) M2M path with missing/invalid `ScopeM2MReadChart`, (c) downstream AMI/billing errors mapped to correct HTTP codes via `handler.Wrap`.
7. **Add observability if absent** — Ensure the route group includes request-scoped tracing and a latency histogram tagged by route template (`/v4/charts/{premises_id}`), not raw URL.
8. **Right-size the payload limit** — Consider reducing the 5 MB `LimitPayload` for this read-only group, or split it so chart GETs use a smaller cap.
