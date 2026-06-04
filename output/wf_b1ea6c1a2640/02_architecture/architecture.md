# Architecture

_Agent: `architect` (Software Architect)_  
_Status: `success` · attempts: 1_

---

I cannot read additional files directly, so I will base the analysis on the routes file content provided in the input. Here is the architectural breakdown of `/v4/charts/{premises_id}`.

---

## Architecture of `/v4/charts/{premises_id}`

### Layering (top → bottom)

1. **Routing layer** — `internal/app/v4/routes.go`
   The endpoint is mounted twice by a single `Router` function that groups everything under chi:
   - **External / end‑user variant**: `r.Get("/v4/charts/{premises_id}", handler.Wrap(usage.Charts))` inside the `authenticated` → details‑required subgroup. Marked implicitly deprecated (the parent `authenticated` group carries a "remove 3 months after moving behind mulesoft" comment).
   - **Internal / M2M variant**: `r.With(basiciam.RequireClaimScope(auth0.ScopeM2MReadChart)).Get("/charts/{premises_id}", handler.Wrap(usage.Charts))` inside the `/v4/user` route, mounted under the `internal` (machine‑to‑machine) group.

2. **Middleware chain** (per variant)
   - **Outer (`external`)**: `downtime.Middleware()` → `middleware.LimitPayload(5 MB)`.
   - **End‑user branch**: `authc.Middleware{Scope: true, IDToken: true}` (Auth0 ID‑token + scope check) → `bp.DetailsByJWTMiddleware()` (resolves Business‑Partner details from the JWT and injects them into request context).
   - **M2M branch** (different outer chain — does **not** go through `external`): `basiciam.RequireAccessToken(auth0.JWKSKeyFunc)` → `basiciam.RequireClaimAudience(auth0.AudM2M)` → `bp.DetailsByFormMiddleware()` (BP details parsed from form‑data, not JWT) → `basiciam.RequireClaimScope(auth0.ScopeM2MReadChart)`.

3. **Handler layer** — `internal/app/v4/usage/charts.Charts`, registered through `handler.Wrap` (a thin response/error adapter in `internal/pkg/handler`). The same handler symbol serves both variants and therefore must read whatever BP context was placed by the upstream middleware.

4. **Domain / data layer** — not visible in the routes file, but the package layout (`v4/usage`, with sibling files `peercomparison.go`, `billed.go`) plus the parallel v3 implementation at `internal/app/v3/ami/charts.go` strongly implies usage data is sourced from an AMI/billing upstream.

### Modules touched

| Module | Role for this feature |
|---|---|
| `internal/app/v4/usage` | Chart handler + business logic |
| `internal/app/v3/authc` | Auth0 JWT validation middleware |
| `internal/app/v3/bp` | Business‑partner context resolution (two flavors) |
| `internal/app/v3/downtime` | Maintenance/downtime gate |
| `internal/pkg/auth0` | JWKS, audience, scope constants |
| `internal/pkg/handler` | HTTP response/error wrapper |
| `pkg/basiciam` (external SP module) | M2M access‑token & scope/audience enforcement |
| `web.v2/middleware` (external SP module) | Generic middleware (payload limit, etc.) |
| `github.com/go-chi/chi/v5` | Routing |

### External dependencies

- `github.com/go-chi/chi/v5` — HTTP router.
- `code.in.spdigital.sg/sp-digital/golang/web.v2/middleware` — shared web middleware.
- `code.in.spdigital.sg/sp-digital/infinity/pkg/basiciam` — IAM/OAuth2 enforcement.
- Auth0 (via `internal/pkg/auth0` constants + JWKS) for both end‑user and M2M paths.

### How the pieces communicate

- Pure synchronous HTTP. chi mounts the handler; middlewares mutate `r.Context()` to deposit auth claims and BP details; `usage.Charts` reads from that context.
- No queues, events, or RPC visible in the matched files — communication is request‑scoped context propagation.

---

### Structural smells flagged

1. **Cross‑version package coupling.** `v4/routes.go` directly imports `v3/authc`, `v3/bp`, `v3/downtime`. The version namespaces are not isolated, so v4 cannot evolve independently of v3 — a breaking change in `v3/bp` is a breaking change for `/v4/charts/{premises_id}`. This is the dominant structural risk.

2. **Same handler bound to two contracts.** `usage.Charts` is registered on both the JWT‑authenticated route and the M2M route, but those routes inject BP details via *different* middlewares (`DetailsByJWTMiddleware` vs `DetailsByFormMiddleware`). The handler must contain a branch (or rely on a context key that may be empty), which is a classic "polymorphic handler" smell — its contract is implicit and only enforceable at runtime.

3. **God router file.** `routes.go` registers every v4 feature (charts, smrd, greengoals, pledge, byob, emailsubscription, account, user) in one function tree. Adding/removing a route forces an edit to a shared file across teams — merge contention and an unclear ownership boundary.

4. **Duplicate public surface for the same capability.** The chart endpoint exists at both `/v4/charts/{premises_id}` (deprecated, end‑user) and `/v4/user/charts/{premises_id}` (M2M). The deprecated route is still active with no removal date, doubling the attack/test surface.

5. **Implicit middleware ordering.** Handler correctness depends on the order `authc → bp.DetailsByJWT*` (or `basiciam → bp.DetailsByForm*`). There is no compile‑time guard; a future refactor that reorders or omits `bp.Details*` would silently produce nil‑context bugs in the handler.

6. **Mixed authentication models behind one path prefix.** Putting JWT‑auth and M2M client‑credential auth under the same `/v4` prefix with overlapping resources makes scope/audience reasoning harder than a clean `/v4/external/...` vs `/v4/internal/...` split would.

7. **Payload limit applies only to the external group.** `middleware.LimitPayload(5MB)` is set in `external` but not in `internal`. For a GET this is moot, but for the wider v4 surface this asymmetry is an easy source of operational surprise.

No cyclic packages are visible from the routes file alone, but the `v3 → v3`, `v4 → v3` direction is fine; the risk would be any back‑edge from `v3` to `v4` (not visible here, but worth verifying when the full handler files are accessible).
