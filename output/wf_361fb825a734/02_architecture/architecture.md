# Architecture

_Agent: `architect` (Software Architect)_  
_Status: `success` · attempts: 1_

---

# Architecture Analysis — `GET /v4/charts/{premises_id}`

Scope is limited to the files that participate in this single endpoint, based on the route registration in `internal/app/v4/routes.go:68` and the surrounding feature files.

## Layering (top → bottom)

1. **Process entry** — `cmd/serverd/main.go` → `cmd/serverd/router/router` (`handler.go`, `gateway.go`) bootstraps the chi mux and mounts the v4 router. A separate `cmd/sapaccnum/main.go` exists as a sibling binary; it is in the scan but does not participate in this endpoint.
2. **Routing / composition** — `internal/app/v4/routes.go` registers `/v4/charts/{premises_id}` once in the *external authenticated* group and a second time inside `/v4/user` for *internal M2M* (line ~110), both pointing at the **same** `usage.Charts` handler.
3. **HTTP adapter / wrapping** — `internal/pkg/handler.Wrap` is the only thing between chi and the feature package. It is the seam that turns the feature's typed handler into an `http.HandlerFunc` (error → JSON, etc.).
4. **Feature module** — `internal/app/v4/usage/` (charts.go, charts_response.go, errors.go, plus billed.go and peercomparison.go that share the package). This is the only domain-aware code path for the endpoint.
5. **Persistence / domain models** — `internal/models/*.go`. The AMI-related models are the ones materially involved here: `ami_meter`, `ami_meter_smmu`, `ami_meter_demo`, `ami_interval_elec`, `ami_interval_gas`, `ami_interval_water`, plus `premises_configs`. Schema for these lives in `data/migrations/0005_.up.sql`.
6. **Side-channel** — `internal/kafka/common.go` is in scope, suggesting the chart flow (or a sibling in `usage`) emits an event after a successful read.

## Middleware chain for the public (`/v4/charts/{premises_id}`) variant

`downtime.Middleware` → `middleware.LimitPayload(5 MiB)` → `authc.Middleware{Scope:true, IDToken:true}` (Auth0-backed) → `bp.DetailsByJWTMiddleware` (resolves business-partner details from the JWT and stashes them in context) → `handler.Wrap(usage.Charts)`.

## Middleware chain for the M2M (`/v4/user/charts/{premises_id}`) variant

`basiciam.RequireAccessToken(auth0.JWKSKeyFunc)` → `basiciam.RequireClaimAudience(auth0.AudM2M)` → `bp.DetailsByFormMiddleware` → `basiciam.RequireClaimScope(auth0.ScopeM2MReadChart)` → `handler.Wrap(usage.Charts)`.

Same business logic, two completely different auth/identity-resolution paths. The handler must read BP identity from a context key that both middlewares are expected to set the same way.

## External dependencies in play

- `github.com/go-chi/chi/v5` — HTTP routing.
- `code.in.spdigital.sg/sp-digital/golang/web.v2/middleware` — payload-limit middleware.
- `code.in.spdigital.sg/sp-digital/infinity/pkg/basiciam` — M2M token enforcement.
- `internal/pkg/auth0` — JWKS / audience / scope constants for Auth0.
- Kafka client (via `internal/kafka`).
- Postgres (inferred from `data/migrations/0005_.up.sql` and the `models` package).

## How the pieces communicate

- **In-process**: chi router → middleware chain → wrapped handler. Identity flows via `context.Context` (set by `bp.DetailsByJWT…` / `bp.DetailsByForm…`).
- **Out-of-process**: Auth0 (JWKS fetch + claim validation), Postgres (AMI interval + meter + premises_configs reads), and Kafka (`internal/kafka/common.go`, likely produce-side for a usage/audit event).

## Structural smells

1. **v4 depends on v3 internals.** `internal/app/v4/routes.go` imports `internal/app/v3/authc`, `internal/app/v3/bp`, and `internal/app/v3/downtime`. The v3 package is explicitly marked `Deprecated:` ("will be removed 3 months after moving behind mulesoft") yet the v4 charts endpoint relies on it. Either the deprecation marker is stale or v4 will break when v3 is removed — this is a real migration-debt risk for this endpoint.
2. **Duplicated handler binding with divergent middleware.** `usage.Charts` is mounted twice. Auth, identity extraction, and downtime behaviour differ between the two mounts. Any change in how the handler reads BP identity from context must be kept in lockstep across both middleware families — easy to drift.
3. **`internal/models` is a god package.** The scan pulls in `orders`, `products`, `pledges`, `districts`, `byob_redemptions`, `capitastar_ebill_promo`, `oem_signup_applications`, `email_subscriptions`, `pilot_user`, `downtime_schedule`, etc. None of these are conceptually related to the chart endpoint; they only appear because every model lives under one flat namespace. Classic anaemic, non-feature-scoped models package — refactoring the chart read path is harder than it should be because the package surface is enormous.
4. **`usage` package mixes concerns.** Charts, billed-usage, and peer-comparison all sit in the same package (`charts.go`, `billed.go`, `peercomparison.go`) sharing `errors.go`. Fine while small, but the package is the obvious next "god module" — three independent read use-cases bound by package-private helpers will resist extraction.
5. **`internal/kafka/common.go` as a shared utility.** A `common` Kafka file is typical god-utility shape; if the chart handler produces an event through it, the coupling between the feature and global Kafka wiring is implicit rather than via a feature-owned producer interface.
6. **Three AMI commodity flavours (elec/gas/water) modelled as parallel tables/models.** `ami_interval_elec.go`, `ami_interval_gas.go`, `ami_interval_water.go` are siblings — likely near-duplicated read paths inside the handler. Worth confirming whether a polymorphic interval model would collapse the duplication.
7. **No visible service/repository layer in the scan.** The path is route → handler → models. If `usage.Charts` reaches directly into `internal/models/ami_interval_*` and `premises_configs`, there is no domain seam to mock — testing (`charts_test.go` is present) likely depends on a real DB or package-level test doubles.

## What I cannot confirm from the scan alone

The handler body (`usage/charts.go`), the wrapper signature (`internal/pkg/handler`), and whether Kafka is actually called on this path were not in the supplied content (the input was truncated and I do not have read permission for those files in this turn). The smells above are inferred from package structure, imports, and the route file; the handler internals may either confirm or relax (4), (5), and (7).
