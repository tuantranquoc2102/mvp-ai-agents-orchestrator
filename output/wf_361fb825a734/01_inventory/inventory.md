# Inventory

_Agent: `researcher` (Research Specialist)_  
_Status: `success` · attempts: 1_

---

# Codebase Inventory — Feature `/v4/charts/{premises_id}`

## Scope & Size
- **Repository**: `jarvis-api` (Go service at `F:\02_SPG_PROJECTS\jarvis-api`)
- **Feature-scoped footprint**: 30 files, ~589 KB total
- **Languages (feature scope)**: Go 29 files (~97%), SQL 1 file (~3%)

## Route Registration (the feature's anchor)
The endpoint is declared in **`internal/app/v4/routes.go`** and is mounted in **two distinct router groups**, both pointing at the same handler `usage.Charts`:

1. **External / authenticated** (line 68) — under `external → authenticated` group:
   - `r.Get("/v4/charts/{premises_id}", handler.Wrap(usage.Charts))`
   - Middleware chain: `downtime.Middleware` → `LimitPayload(5MB)` → `authc.Middleware{Scope, IDToken}` → `bp.DetailsByJWTMiddleware`
   - Marked as the legacy/Deprecated path "to be removed 3 months after moving behind mulesoft."

2. **Internal / M2M (OAuth2)** — under `internal` group at `/v4/user`:
   - `r.With(basiciam.RequireClaimScope(auth0.ScopeM2MReadChart)).Get("/charts/{premises_id}", handler.Wrap(usage.Charts))`
   - Middleware chain: `basiciam.RequireAccessToken(auth0.JWKSKeyFunc)` → `RequireClaimAudience(auth0.AudM2M)` → `bp.DetailsByFormMiddleware` → scope guard `ScopeM2MReadChart`

The actual handler implementation lives in package `internal/app/v4/usage` (referenced via `usage.Charts`) — that package is the natural next read for behavior details.

## Likely Entry Points
- **`cmd/serverd/main.go`** — primary HTTP server binary (matches the `serverd/router/{handler,gateway}.go` siblings that wire chi routes).
- **`cmd/serverd/router/handler.go`** & **`cmd/serverd/router/gateway.go`** — top-level router assembly / gateway wiring that mounts the v4 router.
- **`cmd/sapaccnum/main.go`** — a separate CLI/worker binary (likely SAP account-number related; only tangentially in feature scope).

## Config / Build Files in Scope
- **`cmd/appconfig/default_app_cfg.go`** — application default config (env, dependencies, feature toggles).
- **`internal/kafka/common.go`** — Kafka client/common helpers (the feature touches messaging infra).
- **`data/migrations/0005_.up.sql`** — the only non-Go file; a schema migration relevant to the data model the chart feature consumes.

## Models Touched (data surface for the feature)
A heavy `internal/models/*` cluster appears in scope, indicating the chart endpoint aggregates across multiple domains:
- **AMI / metering**: `ami_meter.go`, `ami_meter_demo.go`, `ami_meter_smmu.go`, `ami_interval_elec.go`, `ami_interval_gas.go`, `ami_interval_water.go` — strongly suggests the chart serves multi-utility (elec/gas/water) interval consumption data per premises.
- **Premises & users**: `premises_configs.go`, `pilot_user.go`.
- **Pledges/Green Goals**: `pledges.go`, `pledge_cycle_results.go`, `distribution_nric.go`, `distribution_items.go`, `distribution_locations.go`, `districts.go`.
- **Commerce/Loyalty**: `orders.go`, `order_items.go`, `products.go`, `byob_redemptions.go`, `capitastar_ebill_promo.go`.
- **Ops/comms**: `email_subscriptions.go`, `downtime_schedule.go`, `oem_signup_applications.go`.

Most of these are likely co-matched because they share an ORM/registration file rather than being directly consumed by `Charts` — confirmation requires reading `internal/app/v4/usage` next.

## Key Observations / Open Questions
- Same handler serves both customer-auth (JWT/Auth0) and M2M (OAuth2 scope-gated) traffic — any behavior change to `usage.Charts` impacts both consumer surfaces.
- The external mount is explicitly slated for retirement once Mulesoft fronting is complete; internal M2M route is the long-lived path.
- The 30-file match list is router-/registration-anchored; the real implementation depth (DB queries, AMI aggregation logic) is in the `internal/app/v4/usage` package, which was **not** included in the truncated content — that's the priority for the next research step.
