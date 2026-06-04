# Report

_Agent: `assistant` (General Assistant)_  
_Status: `success` · attempts: 1_

---

# Final Analysis — `GET /v4/charts/{premises_id}`

## Overview

`GET /v4/charts/{premises_id}` is a multi-utility chart endpoint in the `jarvis-api` Go service that returns AMI interval consumption data (electric, gas, water) for a premises. It is the only handler in the feature scan that is registered **twice** against the same implementation, and is therefore a dual-surface endpoint:

- **External / customer path** — `internal/app/v4/routes.go:68`, mounted under the `external → authenticated` group with Auth0 JWT + ID-token scope checks (`authc.Middleware`), payload cap (`LimitPayload(5MB)`), downtime gating (`downtime.Middleware`), and a JWT-derived premises lookup (`bp.DetailsByJWTMiddleware`). This route is annotated in routes.go as deprecated — to be removed three months after Mulesoft fronting is in place.
- **Internal / M2M path** — registered inside the `internal` group at `/v4/user/charts/{premises_id}` with `basiciam.RequireAccessToken(auth0.JWKSKeyFunc)`, `RequireClaimAudience(auth0.AudM2M)`, `bp.DetailsByFormMiddleware`, and the scope guard `auth0.ScopeM2MReadChart`. This is the long-lived path.

Both routes resolve to `usage.Charts` in package `internal/app/v4/usage`. Any behavior change to that single function affects both consumer surfaces simultaneously.

The handler is wrapped by `internal/pkg/handler.Wrap`, which is the only adapter between chi and the feature package (typed handler → `http.HandlerFunc`, error → JSON envelope).

## Architecture

**Layering (top → bottom):**

1. **Process entry** — `cmd/serverd/main.go`, with router assembly in `cmd/serverd/router/handler.go` and `cmd/serverd/router/gateway.go`. (`cmd/sapaccnum/main.go` is co-matched in scope but does not participate in this endpoint.)
2. **Routing / composition** — `internal/app/v4/routes.go` is the sole composition point; it picks the auth posture per mount and shares the downstream handler.
3. **HTTP adapter** — `internal/pkg/handler.Wrap` is the only seam between chi and the feature package.
4. **Feature module** — `internal/app/v4/usage/` (charts.go, charts_response.go, errors.go, with sibling `billed.go` and `peercomparison.go` sharing the package). This is the only domain-aware code path for the endpoint.
5. **Persistence / domain models** — `internal/models/` AMI cluster: `ami_meter.go`, `ami_meter_smmu.go`, `ami_meter_demo.go`, `ami_interval_elec.go`, `ami_interval_gas.go`, `ami_interval_water.go`, plus `premises_configs.go`. Schema in `data/migrations/0005_.up.sql`.
6. **Side-channel** — `internal/kafka/common.go` is in scope; the usage package likely emits an event post-read (worth confirming).

**Cross-cutting infra in the request path:**
- Default config: `cmd/appconfig/default_app_cfg.go`
- Common Kafka helpers: `internal/kafka/common.go`
- Migration governing the AMI tables the handler reads: `data/migrations/0005_.up.sql`

**Auth model observation.** The external mount derives the premises context from the JWT (`bp.DetailsByJWTMiddleware`), while the M2M mount derives it from form data (`bp.DetailsByFormMiddleware`). Both then dispatch to the same handler, which means `usage.Charts` must be agnostic to *how* the premises context arrived. This is a healthy split, but it concentrates trust in the middleware — a regression in either `DetailsByJWTMiddleware` or `DetailsByFormMiddleware` would silently change tenant scoping on the shared handler.

**Co-matched but non-participating models.** The inventory pulls in a large `internal/models/*` cluster (pledges, distributions, orders, products, byob_redemptions, ebill promo, oem signups, email subs, downtime schedule). These almost certainly co-match through a shared ORM registration file rather than being consumed by `Charts`. They should be treated as noise for impact analysis.

## Quality & Risk

**1. Dual-mount blast radius (High).** A single handler serves both end-user JWT traffic and M2M traffic. There is no per-surface behavior switch visible at the routes layer, so the handler cannot differentiate "internal partner is fine to see extended fields" vs "customer must be filtered." Any field addition that is sensitive for one surface leaks to both. Mitigation requires either a surface flag plumbed through `handler.Wrap` or a response shaping layer keyed off the auth claims.

**2. Deprecated path still live (Medium).** The external `/v4/charts/{premises_id}` mount is marked for removal post-Mulesoft cutover. As long as it is mounted, the deprecation comment is the *only* signal — there is no `Deprecation`/`Sunset` HTTP header, no metric, and no scheduled removal date in code. This makes the removal window unenforceable.

**3. Schema coupling (Medium).** The handler reads from three interval tables (`ami_interval_elec/gas/water`) plus meter metadata (`ami_meter`, `ami_meter_smmu`, `ami_meter_demo`) — six storage shapes for one response. The migration that defines them is a single file (`data/migrations/0005_.up.sql`), so the shapes evolved together originally but there is no compile-time guarantee they still align. Any drift between utility variants (e.g., differing interval granularity) becomes a per-utility branch inside `usage.Charts`.

**4. Payload limit asymmetry (Low/Medium).** `LimitPayload(5MB)` is applied to the external mount only. The internal M2M mount has no comparable cap visible in `routes.go`. For a GET endpoint this is mostly inert, but if the handler ever accepts a POST sibling or grows query-body semantics, the M2M path is unbounded.

**5. Side-effect ambiguity (Low).** `internal/kafka/common.go` being in feature scope suggests the chart path emits Kafka. If `Charts` is producing events on read, that's an observability/analytics concern: failures in Kafka must not fail the read, and retries must not double-emit. This needs explicit confirmation from `internal/app/v4/usage/charts.go`.

**6. Test coverage gap (Unknown — flag for inspection).** No `*_test.go` files appear in the feature inventory. Given that this single handler underpins two distinct auth surfaces, the absence of visible tests in the scan is itself a risk signal worth verifying.

## Recommended Next Steps

1. **Read `internal/app/v4/usage/charts.go` and `charts_response.go` end-to-end.** The inventory and architecture layers are well-understood; the actual aggregation logic, error mapping (`usage/errors.go`), and any Kafka emission are not yet visible. Until this is read, the risk items above are inferred, not confirmed.
2. **Diff the two middleware chains in `routes.go` (lines ~68 and ~110) and document the contract `usage.Charts` must honor.** Confirm whether the handler inspects the auth context to distinguish JWT vs M2M callers, or whether it treats them identically. If identical, decide whether that is intentional.
3. **Make the deprecation enforceable.** Add a `Sunset` header and a per-mount metric (`route="/v4/charts external|internal"`) so the external traffic decay can be observed. Set a hard removal date in the comment at `routes.go:68`.
4. **Add a response-shape contract test that exercises both mounts** against a fixed premises fixture, asserting field parity (or documented divergence). This locks the dual-surface invariant the architecture currently relies on by convention.
5. **Verify the `internal/kafka/common.go` involvement.** Specifically, whether `usage.Charts` is a producer, and if so, whether emission is best-effort wrapped (it should not block or fail the HTTP response).
6. **Prune the `internal/models/*` noise from future scans.** Pin the scan to imports actually reachable from `internal/app/v4/usage` to avoid the pledges/orders/products cluster crowding out signal — only the AMI + `premises_configs` models are materially in this feature's surface.
7. **Confirm `data/migrations/0005_.up.sql` is still the authoritative schema** for the AMI tables the handler reads. If later migrations have altered these tables, the file currently in scope is misleading for impact assessment.
