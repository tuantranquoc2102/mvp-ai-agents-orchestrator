# Architecture

_Agent: `architect` (Software Architect)_  
_Status: `success` · attempts: 1_

---

I can only see the truncated routes.go content from the input; the actual handler `usage.Charts` and dependent packages aren't readable. I'll infer the architecture from the route registration, import graph, and file layout shown in `codebase_scan`.

# Architecture Inference — `/v4/charts/{premises_id}`

## Layering (top → bottom)

1. **HTTP routing layer** — `internal/app/v4/routes.go`
   - `chi/v5` router. `v4.Router` splits traffic into `external` and `internal` groups.
   - `external` → `downtime.Middleware` + 5 MB payload limit → splits again into `authenticated` (JWT) and `public`.
   - `internal` → `basiciam.RequireAccessToken(auth0.JWKSKeyFunc)` + `basiciam.RequireClaimAudience(auth0.AudM2M)`.

2. **Authentication / context-enrichment middleware** — cross-cutting, pulled from `internal/app/v3`
   - `authc.Middleware{Scope, IDToken}` — JWT validation for the external customer path.
   - `bp.DetailsByJWTMiddleware()` — loads Business Partner details from JWT claims (external path).
   - `bp.DetailsByFormMiddleware()` — loads BP details from form data (internal/M2M path).
   - `bp.cache.go` + `bp.context.go` — caches BP details and injects them into `context.Context`.
   - `basiciam.RequireClaimScope(auth0.ScopeM2MReadChart)` — scope check on the M2M path.

3. **Handler wrapper** — `internal/pkg/handler` (`handler.Wrap`)
   - Standard wrapper-around-business-function pattern. Likely normalises errors → HTTP responses and decodes path/query params.

4. **Feature handler** — `internal/app/v4/usage.Charts` in `internal/app/v4/usage/charts.go`
   - The single endpoint handler. Reused unchanged for both mount points.
   - Sibling files (`peercomparison.go`, `billed.go`) suggest `usage` is the "consumption analytics" bounded context.

5. **Domain / data access (inferred, not in scan)** — the handler almost certainly delegates to AMI/billing services. `internal/app/v3/ami/charts.go` is in the scan, which strongly suggests `v4/usage.Charts` calls into `v3/ami` for the underlying meter-data retrieval — i.e. v4 is a façade re-exposing v3 functionality.

## Two mount points for one handler

```
External (customer):   GET /v4/charts/{premises_id}
   downtime → LimitPayload(5MB) → authc(JWT) → bp.DetailsByJWT → handler.Wrap(usage.Charts)

Internal (M2M):        GET /v4/user/charts/{premises_id}
   basiciam.RequireAccessToken → RequireClaimAudience(M2M)
   → bp.DetailsByForm → RequireClaimScope(M2MReadChart) → handler.Wrap(usage.Charts)
```

Both paths converge by writing BP details into `ctx`; `usage.Charts` reads from `ctx` and is therefore source-agnostic. Good separation, but see smells below.

## External dependencies / modules

- `code.in.spdigital.sg/sp-digital/golang/web.v2/middleware` — payload limiter.
- `code.in.spdigital.sg/sp-digital/infinity/pkg/basiciam` — M2M auth primitives (token + audience + scope).
- `github.com/go-chi/chi/v5` — router.
- Local: `internal/app/v3/{authc,bp,downtime,ami}`, `internal/pkg/{auth0,handler}`.

## Inter-component communication

- Synchronous, in-process. All wiring is through `context.Context` (BP details, auth claims) and direct function calls. No queue/bus involved on this path.
- Cross-cutting state for BP details is keyed in `bp/context.go`; `bp/cache.go` indicates an in-memory cache to avoid re-looking up BP each request.

## Structural smells

1. **Versioned packages depend on older versioned packages.** `v4/routes.go` imports `v3/authc`, `v3/bp`, `v3/downtime`. `v3` has implicitly become a shared "platform" layer rather than a frozen API version. Risk: a behavioural change made for v3 callers leaks into v4/v5. Suggested fix — promote these to `internal/pkg/{authc,bp,downtime}` so the dependency is explicit and unversioned.

2. **Same handler mounted twice with different middleware stacks.** `usage.Charts` is wired under both `/v4/charts/{premises_id}` (JWT/customer) and `/v4/user/charts/{premises_id}` (M2M). The handler must remain ignorant of which path called it. There's no compile-time guarantee that future edits won't add a code path that only works for one source of BP details (e.g. assumes `IDToken` claims are present). Worth a small interface/contract test that exercises both mounts (the scan shows `charts_test.go` exists — verify both contexts are covered).

3. **Likely v4 → v3 call-through for domain logic.** `v3/ami/charts.go` being in the scan implies `v4/usage.Charts` calls into `v3/ami`. If true, v4 is largely a re-skinned v3 with new middleware, which dilutes the meaning of versioning. Not a bug, but a flag for the team: decide whether v4 should own its handler logic or formally declare v3 packages as the shared service layer.

4. **Cross-cutting concerns scattered across two middleware vendors.** `authc` (local) for external auth vs `basiciam` (infinity package) for M2M auth — different abstractions for very similar work. Two auth styles co-existing is fine; just be aware divergence increases surface area for auth bugs.

5. **Route file is the composition root and is growing.** `v4/routes.go` registers middleware *and* enumerates every route. Already mixes deprecated (`/v4/pledge/status`) with current routes inline. Not cyclic, not a god module yet, but it's the natural place that will become one. Splitting per-feature route registration (`usage.Register(r)`, `greengoals.Register(r)`) keeps the composition root thin.

6. **`bp.cache.go` is shared across auth modes.** Two different middlewares (`DetailsByJWT`, `DetailsByForm`) presumably populate the same cache. Cache-key collisions or TTL semantics for M2M vs end-user lookups deserve a look — couldn't verify without reading `bp/cache.go`.

No cyclic packages are visible from the import list (`v4 → v3`, no reverse edges shown). No god module on this path yet — `usage` has 3 files, `routes.go` is ~150 lines.
