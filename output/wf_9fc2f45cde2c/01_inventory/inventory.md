# Inventory

_Agent: `researcher` (Research Specialist)_  
_Status: `success` · attempts: 1_

---

# Codebase Inventory — `/v4/charts/{premises_id}` Feature Scope

## Language & Size
- **Language:** 100% Go (70/70 files)
- **Total size:** ~721 KB across 70 files in scope
- **Module root:** `F:\02_SPG_PROJECTS\jarvis-api` (module path `code.in.spdigital.sg/sp-digital/jarvis-api`)

## Feature Surface Area
The route `/v4/charts/{premises_id}` lives within a versioned API layout under `internal/app/v{1..5}`. Only **v4** is the active surface for this feature; v3 packages are pulled in because v4 reuses v3 middleware/handlers, and v1/v2/v5 routes.go are present as siblings in the routing tree.

## Likely Entry Points (in execution order)
1. **`internal/app/v4/routes.go`** — registers v4 routes via `chi.Router`. Line 68 is the matched line where the `/v4/charts/{premises_id}` route is mounted under the "Details-required" group, behind:
   - `downtime.Middleware()`
   - `middleware.LimitPayload(5MB)` (from `web.v2`)
   - `authc.Middleware{Scope, IDToken}` (auth0-based)
   - `bp.Details(...)` (Business-Partner / premise resolution middleware)
2. **`internal/app/v4/usage/charts.go`** — the handler implementation for the feature (paired test: `charts_test.go`).
3. **`internal/app/v3/bp/*`** — heavily referenced supporting package: `middleware.go`, `details.go`, `details_methods.go`, `load.go`, `cache.go`, `context.go`, `meter.go`, `retrieve.go`, `shared.go`, `verifycache.go`, `grouped.go`. This is the premise-details pipeline that supplies context (premise ID, meters, BP info) consumed by the charts handler.

## Notable Top-Level Groupings in Scope
- **v4 packages:** `usage` (the feature lives here), `account`, `user`, `smrd`, `greengoals`, plus references to `byob`, `emailsubscription`, `pledge` via routes.go imports.
- **v3 reused packages:** `bp` (premise details — central dependency), `authc` (authentication), `downtime`, `ami` (smart-meter charts — `ami/charts.go`), `ppms` (`ppms/charts.go`), `smrd`, `datastream`, `ebill`, `oem`, `bill`, `broadcast`, `premise`, `account`.

## Config / Build / Framework Signals
- **HTTP router:** `github.com/go-chi/chi/v5`.
- **Shared middleware/handler libs:** `code.in.spdigital.sg/sp-digital/golang/web.v2/middleware`, `internal/pkg/handler` (uses `handler.Wrap`), `internal/pkg/auth0`, `pkg/basiciam`.
- No build/config files (go.mod, Makefile, Dockerfile, CI yaml) appear in this filtered scope — the scan was scoped to feature-relevant Go sources only.

## Test Coverage Signals
Test pairing is consistent (`*_test.go` alongside source) across the BP pipeline and v4 handlers. Direct test for the feature: **`internal/app/v4/usage/charts_test.go`**. Sibling chart implementations exist in `v3/ami/charts.go` and `v3/ppms/charts.go` (with tests) — useful as comparative references but not the v4 route under analysis.

## Architectural Read
The feature is a thin v4 HTTP handler (`v4/usage/charts.go`) layered on top of a substantial v3 "premise details" middleware/cache stack (`v3/bp/*`) that resolves `{premises_id}` into authenticated, meter-aware request context before the chart handler runs. Authentication and payload limits are layered at the v4 router level.
