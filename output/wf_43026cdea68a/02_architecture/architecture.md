# Architecture

_Agent: `architect` (Software Architect)_  
_Status: `success` · attempts: 1_

---

# Architecture Analysis — `/v4/charts/{premises_id}`

Based on the pre-filtered codebase scan and the visible content of `internal/app/v4/routes.go`, here is the inferred architecture for this specific endpoint.

## 1. Endpoint placement

- **Route**: `GET /v4/charts/{premises_id}` is registered inside `internal/app/v4/routes.go` (line 68), under the **authenticated → details-required** group.
- **Router**: `github.com/go-chi/chi/v5`. Routes are composed via nested `r.Group(...)` calls.
- **Handler entry**: dispatched through `handler.Wrap(...)` (`internal/pkg/handler`) to the function in `internal/app/v4/usage/charts.go` (paired with `charts_test.go`).

## 2. Layering (top → bottom)

| Layer | Components for this feature |
|---|---|
| **Transport / routing** | `internal/app/v4/routes.go` (chi groups: external → authenticated → details-required) |
| **Cross-cutting middleware** | `downtime.Middleware()` (v3), `middleware.LimitPayload(5MB)` (`web.v2`), `authc.Middleware{Scope:true, IDToken:true}` (v3), `bp.DetailsByJWTMiddleware()` (v3) |
| **Handler** | `internal/app/v4/usage/charts.go` — function passed to `handler.Wrap` |
| **Domain / shared service** | `internal/app/v3/bp` (Billing-Premises details, cache, retrieve, sort, meter, enrolment, etc.) injects the `premises_id`-resolved BP context into the request before the handler runs |
| **Infra glue** | `internal/pkg/handler` (response/error envelope), `internal/pkg/auth0` (token helpers used indirectly via `authc`) |

The handler is a thin orchestrator: middleware pre-loads BP details by JWT + `premises_id`; the handler reads them from request context (`v3/bp/context.go`) and assembles the chart response (response shape lives in `v3/ami/charts_response.go`, suggesting v4/usage/charts reuses the AMI charts payload model).

## 3. Module communication

```
client
  │  HTTP GET /v4/charts/{premises_id}
  ▼
chi router (v4/routes.go)
  │── downtime.Middleware
  │── LimitPayload
  │── authc.Middleware (JWT scope + ID token)
  │── bp.DetailsByJWTMiddleware ──► context.WithValue(bpDetails)
  ▼
handler.Wrap → v4/usage/charts.Handler
  │   reads bp.FromContext(r.Context())
  │   → builds usage/chart query (likely calls v3/ami or downstream)
  ▼
Response (JSON via internal/pkg/handler)
```

Communication is **in-process function calls + `context.Context` value passing** — no message bus, no internal RPC. External dependencies (downstream services for AMI/usage data) are reached from inside `v4/usage` or via shared clients pulled from the `bp` chain.

## 4. External dependencies (in scope of this feature)

- `github.com/go-chi/chi/v5` — routing.
- `code.in.spdigital.sg/sp-digital/golang/web.v2/middleware` — payload limit / generic middleware.
- `code.in.spdigital.sg/sp-digital/infinity/pkg/basiciam` — IAM primitives (imported by v4 routes).
- Auth0 (via `internal/pkg/auth0`, exercised by `authc`).
- Whatever AMI/usage backend the `v3/ami` and `v3/bp` retrieval functions call (the scan only shows the Go wrapper layer).

## 5. Structural smells

1. **Cross-version coupling (v4 → v3).** `internal/app/v4/routes.go` imports `v3/authc`, `v3/bp`, `v3/downtime`. The v4 namespace is not an isolated version — it is an incremental façade over v3 infrastructure. This is fine pragmatically, but means any breaking change in `v3/bp` simultaneously affects v3, v4, and v5 routes (v5 routes file is also in scope), making the "version" abstraction misleading.

2. **`v3/bp` is a god module.** The scan shows 20+ files in `v3/bp/`: `cache`, `context`, `details`, `details_methods`, `enrolment`, `getbpdetails`, `grouped`, `load`, `meter`, `middleware`, `removecache`, `retrieve`, `shared`, `sort`, `verifycache` (each with a `_test.go`). Responsibilities span HTTP middleware, caching, sorting, meter logic, and enrolment — multiple bounded contexts collapsed into one package. Any change to `bp` ripples across every authenticated route in v3/v4/v5.

3. **Middleware does work that belongs to the handler.** `bp.DetailsByJWTMiddleware()` resolves and loads BP details into context. The handler then re-reads them. This couples the handler's correctness to a side-effect of a middleware several layers up; if the route were ever moved out of the `Details-required` group, the handler would silently get a nil context value rather than fail at the type system level.

4. **Comment/code drift on the auth layer.** The visible `routes.go` excerpt marks `authenticated` as `// Deprecated: ... will be removed 3 months after moving behind mulesoft`, yet `/v4/charts/{premises_id}` still sits behind it. This signals dual auth strategies in flight — the endpoint may need to be re-tested under whichever group survives.

5. **Response model reuse across versions (`v3/ami/charts_response.go` consumed from `v4/usage/charts.go` indirectly).** Mixing v3 response shapes into v4 handlers makes versioned API contracts harder to evolve independently.

6. **No visible domain layer.** Handlers call shared packages directly; there is no separation between HTTP-shape concerns and domain logic. `v4/usage/charts.go` is both the controller and (likely) the use case. Acceptable for a small endpoint, but the `bp` god-package pattern shows what happens when this grows.

## 6. What this means for further work on this endpoint

- Any modification to charts must verify behavior under `bp.DetailsByJWTMiddleware`'s caching (`v3/bp/cache.go`, `verifycache.go`, `removecache.go`) — silent cache reuse is the most likely source of regressions.
- Changes to the response shape will touch `v3/ami/charts_response.go`, which is shared; isolate via a v4-local DTO before evolving.
- If a v5 successor is planned, decoupling from `v3/bp` should be sequenced first; otherwise v5 will inherit the same god-module dependency.
