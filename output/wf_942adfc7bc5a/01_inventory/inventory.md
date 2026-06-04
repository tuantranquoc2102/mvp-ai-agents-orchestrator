# Inventory

_Agent: `researcher` (Research Specialist)_  
_Status: `success` · attempts: 1_

---

# Codebase Inventory Summary — Feature `/v4/charts/{premises_id}`

## Scope & Scale (pre-filtered to feature)
- **Repository**: `jarvis-api` (Go service)
- **Files in feature scope**: 30 files
- **Total size**: 280,675 bytes (~274 KB)
- **Language distribution**: 100% Go (30/30 files)
- **Path concentration**: All under `internal/app/` across versioned packages (`v1`–`v5`), with the active implementation centered in `v4`

## Likely Entry Points

### Primary route registration
- **`internal/app/v4/routes.go`** — Registers the feature endpoint at line 68:
  ```go
  r.Get("/v4/charts/{premises_id}", handler.Wrap(usage.Charts))
  ```
  - Mounted under the **authenticated external group** with middleware chain: `downtime.Middleware` → `LimitPayload(5MB)` → `authc.Middleware` (Scope + IDToken) → `bp.DetailsByJWTMiddleware`
  - Also exposed as an **internal M2M route** at `/v4/user/charts/{premises_id}` (same `usage.Charts` handler) gated by `basiciam.RequireAccessToken` + `auth0.ScopeM2MReadChart` + `bp.DetailsByFormMiddleware`

### Handler implementation
- **`internal/app/v4/usage/charts.go`** — The `usage.Charts` handler function (the feature's core logic)
- **`internal/app/v4/usage/charts_test.go`** — Test coverage for the handler

### Related sibling versions (referenced for context, not the active path)
- `internal/app/v3/ami/charts.go` + `charts_test.go` — v3 predecessor in the AMI package
- `internal/app/v1/routes.go`, `v2/routes.go`, `v3/routes.go`, `v5/routes.go` — version peers (likely showing route evolution / where this endpoint exists or doesn't)

## Notable Supporting Files (shared dependencies)

| Path | Role |
|---|---|
| `internal/app/v3/bp/context.go` + `cache.go` | BP (Business Partner) details middleware that injects premises/account context — required by the route group |
| `internal/app/v3/authc/...` (referenced) | Authentication middleware (`Scope`, `IDToken`) |
| `internal/app/v3/downtime/...` (referenced) | Downtime gate middleware |
| `internal/pkg/handler` (referenced) | `handler.Wrap` adapter that bridges typed handlers to `chi.Handler` |
| `internal/pkg/auth0` (referenced) | JWKS key function + M2M scope constants (`ScopeM2MReadChart`, `AudM2M`) |
| `internal/app/v4/usage/peercomparison.go`, `billed.go` | Sibling handlers in the same `usage` package — likely share helpers/types with `charts.go` |
| `internal/app/v4/account/all.go`, `user/accounts.go`, `greengoals/*.go`, `smrd/*.go` | Co-mounted v4 handlers; pulled in because they share the same route group / middleware stack |

## Config / Build Files
**None present in the feature-filtered scope.** The pre-filter is intentionally narrow to files referencing `/v4/charts/{premises_id}`, so module-level files (`go.mod`, `go.sum`, `main.go`, Dockerfiles, CI configs) are excluded. The `chi/v5` router and `code.in.spdigital.sg/sp-digital/golang/web.v2` framework imports indicate a standard Go HTTP service built on `go-chi`.

## Key Observations
1. **Dual mounting**: The same `usage.Charts` handler serves both an end-user JWT-authenticated path (`/v4/charts/{premises_id}`) and an M2M OAuth2 path (`/v4/user/charts/{premises_id}`) — auth modes differ but business logic is shared.
2. **Versioning pattern**: API uses URL-versioned packages (`v1`–`v5`). The feature lives in v4; v3 has an older `ami/charts.go` ancestor.
3. **Middleware dependency**: The handler depends on `bp.DetailsByJWTMiddleware` (external) or `bp.DetailsByFormMiddleware` (internal) populating BP context — `charts.go` likely reads premises/account info from request context rather than parsing the URL param directly.
4. **Test coverage exists** at both v4 (`usage/charts_test.go`) and v3 (`ami/charts_test.go`) levels.
