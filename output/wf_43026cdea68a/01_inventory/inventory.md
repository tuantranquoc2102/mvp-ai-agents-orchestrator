# Inventory

_Agent: `researcher` (Research Specialist)_  
_Status: `success` · attempts: 1_

---

# Codebase Inventory — Feature `/v4/charts/{premises_id}`

## Inventory Scope
- **Pre-filtered file set:** 70 files, ~591 KB, **100% Go** (single-language scope).
- **All files live under `internal/app/v{1..5}/...`** — this is a versioned HTTP API service. The feature lives in `v4`, but pulls heavily from `v3/bp` (premises/business-partner details) and `v3/ami` (charts plumbing).
- No build files, no go.mod, no Dockerfiles, no CI configs were in the scoped 70 — they exist in the repo but were filtered out as not feature-relevant.

## Dominant Layout Pattern
```
internal/app/
├── v1/routes.go                  # legacy
├── v2/routes.go                  # legacy
├── v3/
│   ├── routes.go
│   ├── account/  link.go
│   ├── ami/      charts.go, charts_response.go, bdl.go, emds.go, srlpmech.go, download.go
│   ├── bill/     retrieve_average_bill.go
│   └── bp/       details.go, details_methods.go, middleware.go, cache.go, load.go, sort.go,
│                 retrieve.go, meter.go, enrolment.go, shared.go, context.go,
│                 grouped.go, getbpdetails.go, removecache.go, verifycache.go
├── v4/
│   ├── routes.go                 # ← registers /v4/charts/{premises_id}
│   ├── account/   all.go, outstanding.go, errors.go
│   ├── greengoals/ districts.go, district_consumption.go, targets.go
│   ├── smrd/      submit.go
│   ├── usage/     charts.go, billed.go, peercomparison.go   ← chart handler
│   └── user/      accounts.go
└── v5/routes.go
```
Each version exposes a `Router(chi.Router)` that the application's main entrypoint wires in. The pattern is one `routes.go` per version + one package per domain.

## Notable Top-Level Files (in scope)
| File | Role |
|---|---|
| `internal/app/v4/routes.go` | **Primary entry point** for the feature. Imports `v4/usage`, `v3/bp`, `v3/authc`, `v3/downtime`. Composes middleware stack (`downtime`, `LimitPayload 5MB`, `authc`, `bp.DetailsByJWTMiddleware`) and mounts the `// Charts` route group. |
| `internal/app/v4/usage/charts.go` | The v4 chart handler implementation (target of the route). |
| `internal/app/v4/usage/charts_test.go` | Handler-level tests. |
| `internal/app/v3/bp/middleware.go` + `details_methods.go` | `DetailsByJWTMiddleware` — resolves premises/BP details from JWT before the handler sees `{premises_id}`. |
| `internal/app/v3/bp/cache.go`, `verifycache.go`, `removecache.go` | Caching layer for premises lookups — likely on the hot path of every chart call. |
| `internal/app/v3/ami/charts.go` + `charts_response.go` | Underlying AMI (Advanced Metering Infrastructure) charts logic that v4 almost certainly delegates to. |

## Entry Points
- **HTTP routing:** `v4.Router(r chi.Router)` → `external` group → `authenticated` group → details-required subgroup guarded by `bp.DetailsByJWTMiddleware()` → `// Charts` route(s). Uses `go-chi/chi/v5`.
- **Handler entry:** `internal/app/v4/usage/charts.go` (wrapped with `handler.Wrap`, the project's standard adapter — visible in the routes file's `pledge.RetrievePledgeStatus` registration).
- **Auth:** `v3/authc.Middleware{Scope: true, IDToken: true}` (Auth0-backed, per `internal/pkg/auth0` import).

## Config / Build Files
None of the 70 scoped files are config/build. The imports reveal the toolchain:
- **Module path:** `code.in.spdigital.sg/sp-digital/jarvis-api` (private SP Digital module).
- **Frameworks/libs:** `github.com/go-chi/chi/v5` (HTTP), `code.in.spdigital.sg/sp-digital/golang/web.v2/middleware`, `code.in.spdigital.sg/sp-digital/infinity/pkg/basiciam`.
- Build/CI/Dockerfile/go.mod would be at repo root — out of feature scope.

## Likely Call Graph for `/v4/charts/{premises_id}`
`chi` router → `downtime` → `LimitPayload(5MB)` → `authc` (Auth0 JWT, scope+IDToken) → `bp.DetailsByJWTMiddleware` (loads premises details, hits `bp/cache.go`) → `handler.Wrap(usage.Charts…)` in `v4/usage/charts.go` → likely calls into `v3/ami/charts.go` for the actual time-series data, then formatted via `v3/ami/charts_response.go`.
