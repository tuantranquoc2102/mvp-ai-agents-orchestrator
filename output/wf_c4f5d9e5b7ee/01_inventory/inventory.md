# Inventory

_Agent: `researcher` (Research Specialist)_  
_Status: `success` · attempts: 1_

---

# Codebase Inventory — `/v4/charts/{premises_id}`

## Inventory at a glance
- **Root**: `F:\02_SPG_PROJECTS\jarvis-api` (Go service — `jarvis-api`)
- **Scope size**: 30 files, ~327 KB pre-filtered to this feature
- **Languages**: Go (29 files) + SQL (1 migration)
- **HTTP framework**: `github.com/go-chi/chi/v5`
- **Auth stack**: SP Digital `basiciam` + Auth0 JWKS (`internal/pkg/auth0`), plus an in-house `authc` middleware

## Entry point for the feature
`internal/app/v4/routes.go` (line 68) is the single registration site:

```go
r.Get("/v4/charts/{premises_id}", handler.Wrap(usage.Charts))
```

- Registered inside the `authenticatedRoutes` group → wrapped by:
  1. `downtime.Middleware()` (outer `external` group)
  2. `middleware.LimitPayload(5MB)` (outer `external` group)
  3. `authc.Middleware{Scope:true, IDToken:true}` (authenticated group — Auth0 ID token)
  4. `bp.DetailsByJWTMiddleware()` (details-required sub-group — loads Business Partner context from JWT)
- There is also a **machine-to-machine twin** at `/v4/user/charts/{premises_id}` in the `internal` group (OAuth2 client-credentials with audience `AudM2M` and scope `ScopeM2MReadChart`) — same `usage.Charts` handler but `bp.DetailsByFormMiddleware()` resolves premises from form data instead of JWT.

## Top-level router wiring
- `cmd/serverd/router/gateway.go` and `cmd/serverd/router/handler.go` are the process-level mount points that chain `v1.Router` → `v5.Router` onto the chi tree. Only `v4.Router` registers this exact path; v3/v5 are present in scope only because they share the `bp` package and sibling chart endpoints (e.g., `v3/ami/charts.go`).

## Handler + supporting packages in scope
- **Handler (referenced, not in matched bundle)**: `internal/app/v4/usage` — `usage.Charts` is the target function. The scan did not include its source file, so the implementation will need to be retrieved separately to confirm internals.
- **BP (Business Partner) context** — all in `internal/app/v3/bp/`, the auth/identity layer the handler depends on:
  - `middleware.go` — `DetailsByJWTMiddleware`, `DetailsByFormMiddleware`
  - `details.go` / `details_methods.go` — premises/account details resolution
  - `load.go`, `grouped.go`, `meter.go` — premises + meter lookups
  - `cache.go` — caching of BP details
  - `context.go` — request-scoped context plumbing
- **AMI charts (v3 sibling, likely shared logic source)**: `internal/app/v3/ami/charts.go`, `download.go` — earlier-version charts implementation; `usage.Charts` likely descends from or delegates to these.
- **Stubs / clients**: `internal/stubs/client.go` (downstream service stubs)
- **Model**: `internal/models/request_nonces.go` (idempotency/nonce tracking)

## Config / build / data
- **Migration in scope**: `data/migrations/0005_.up.sql` — only SQL file pulled in; relevant to the feature's data model.
- No `go.mod`, `Dockerfile`, CI config, or top-level `main.go` appeared in the pre-filtered set — those exist in the repo but are out of feature scope.

## Test coverage already present for the feature surface
Substantial Go test files alongside the production code: `charts_test.go`, `download_test.go`, plus BP-layer tests (`details_methods_test.go`, `grouped_test.go`, `load_test.go`, `context_test.go`, `middleware_test.go`, `meter_test.go`) and adjacent `retrieve_average_bill_test.go`, `account/link_test.go`. Indicates the `bp` middleware chain and v3 AMI charts have established test scaffolding that the v4 handler likely reuses.

## Notable gaps to fetch next
1. **`internal/app/v4/usage/` source** — `usage.Charts` body, request/response shape, and its calls into `bp` + downstream services.
2. **`handler.Wrap`** (`internal/pkg/handler`) — response/error contract for the endpoint.
3. **`authc` and `downtime`** middleware internals — to document the auth contract and outage behavior.
