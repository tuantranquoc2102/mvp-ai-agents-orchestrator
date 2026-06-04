# Inventory

_Agent: `researcher` (Research Specialist)_  
_Status: `success` · attempts: 1_

---

# Codebase Inventory — Feature `/v4/charts/{premises_id}`

## Scope Metrics
- **Root**: `F:\02_SPG_PROJECTS\jarvis-api`
- **Files in scope**: 30 (all Go, 100%)
- **Total size**: ~280 KB (~274 KB)
- **Language**: Go exclusively (no JS/TS, YAML configs, or polyglot artefacts surfaced in this slice)

## Route Registration (Entry Point)
The feature is registered in **`internal/app/v4/routes.go`** (line 68):

```go
r.Get("/v4/charts/{premises_id}", handler.Wrap(usage.Charts))
```

Registered **twice** in the same file under different router groups:
1. **External authenticated route** (line 68) — inside `authenticatedRoutes`, behind:
   - `authc.Middleware{Scope: true, IDToken: true}` (Auth0 JWT)
   - `bp.DetailsByJWTMiddleware()` (business-partner details enrichment)
   - `downtime.Middleware()` + `middleware.LimitPayload(5MB)` (group-level)
2. **Internal M2M route** (`/v4/user/charts/{premises_id}`) — inside `internal()`:
   - `basiciam.RequireAccessToken(auth0.JWKSKeyFunc)`
   - `basiciam.RequireClaimAudience(auth0.AudM2M)`
   - `basiciam.RequireClaimScope(auth0.ScopeM2MReadChart)`
   - `bp.DetailsByFormMiddleware()` (IAM_ID via form data)

Both paths funnel to the **same handler**: `usage.Charts`.

## Likely Entry Points (Handler Layer)
| File | Role |
|---|---|
| `internal/app/v4/routes.go` | Route registration / middleware composition |
| `internal/app/v4/usage/charts.go` | Primary handler implementation (`usage.Charts`) |
| `internal/app/v4/usage/charts_test.go` | Handler unit/integration tests |

## Supporting Modules in Scope
- **Auth / context plumbing**: `internal/app/v3/authc`, `internal/app/v3/bp/{context,cache}.go`, `internal/pkg/handler`, `internal/pkg/auth0`
- **Sibling v4 handlers sharing the same middleware group** (likely co-evolved patterns): `v4/usage/{billed,peercomparison}.go`, `v4/greengoals/{districts,targets}.go`, `v4/smrd/submit.go`, `v4/account/all.go`, `v4/user/accounts.go`
- **Legacy lineage / reference implementations**: `internal/app/v3/ami/charts.go` + `charts_test.go` (v3 predecessor of the charts feature), `v3/ami/download.go`, `v3/bill/retrieve_average_bill.go`, `v3/account/link.go`
- **Version routers (cross-reference only)**: `internal/app/v{1,2,3,5}/routes.go` — pulled in because they share routing scaffolding but do **not** register `/v4/charts/{premises_id}`

## Config / Build Files
**None present in this feature-scoped slice.** No `go.mod`, Dockerfile, CI YAML, or deployment manifests were included in the matched-files set. Build/config investigation requires widening the scan.

## Key Observations for Downstream Analysis
1. **Single handler, dual exposure** — the same `usage.Charts` serves both end-user (Auth0 ID-token) and machine-to-machine (M2M scope) callers; `premises_id` is a URL path parameter in both.
2. **BP details middleware is mandatory** — `bp.DetailsByJWTMiddleware` (external) and `bp.DetailsByFormMiddleware` (internal) populate request context the handler likely depends on; `v3/bp/context.go` + `cache.go` are in scope and warrant review.
3. **v3 → v4 evolution** — `v3/ami/charts.go` is included, suggesting v4 charts is a successor; comparing the two will likely explain v4's contract.
4. **Test coverage is co-located**: every non-trivial handler in scope has a paired `_test.go` (charts, billed, districts, targets, submit, accounts, etc.) — TDD/parallel-test style appears established.
