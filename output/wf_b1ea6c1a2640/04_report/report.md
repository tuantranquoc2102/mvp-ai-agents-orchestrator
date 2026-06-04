# Report

_Agent: `assistant` (General Assistant)_  
_Status: `success` · attempts: 1_

---

# Final Analysis Report — `/v4/charts/{premises_id}`

## Overview

The `/v4/charts/{premises_id}` endpoint is a Go-based HTTP route in the `jarvis-api` service that returns chart data scoped to a specific premises identifier. It is the v4 successor of the legacy charts implementation found at `internal/app/v3/ami/charts.go`, and it is the only route in scope that is registered **twice** under different middleware groups while resolving to the same handler symbol — `usage.Charts` in `internal/app/v4/usage/charts.go`.

The feature is implemented entirely in Go (30 files, ~280 KB) with co-located test coverage (`internal/app/v4/usage/charts_test.go`). Two distinct caller classes are supported through one handler:

- **End-user / external callers** authenticated via Auth0 ID-token at `/v4/charts/{premises_id}`.
- **Machine-to-machine (M2M) callers** authenticated via Auth0 access-token + scope `auth0.ScopeM2MReadChart` at `/v4/user/charts/{premises_id}`.

No build/config artifacts (`go.mod`, Dockerfiles, CI YAML) were captured in the pre-filtered slice, so deployment and dependency posture cannot be assessed here.

## Architecture

### Routing & Middleware Composition (`internal/app/v4/routes.go`)

The endpoint is mounted by a single `Router` function and inherits two distinct middleware stacks:

**External variant** (line 68, `authenticatedRoutes` group):
```
downtime.Middleware()
  → middleware.LimitPayload(5MB)
    → authc.Middleware{Scope: true, IDToken: true}      // Auth0 ID-token
      → bp.DetailsByJWTMiddleware()                      // BP context from JWT
        → handler.Wrap(usage.Charts)
```

**Internal / M2M variant** (mounted under `internal()` → `/v4/user`):
```
basiciam.RequireAccessToken(auth0.JWKSKeyFunc)
  → basiciam.RequireClaimAudience(auth0.AudM2M)
    → basiciam.RequireClaimScope(auth0.ScopeM2MReadChart)
      → bp.DetailsByFormMiddleware()                     // BP context from form-data
        → handler.Wrap(usage.Charts)
```

### Layering

1. **Routing** — chi router groups in `internal/app/v4/routes.go`.
2. **Auth / context plumbing** — `internal/app/v3/authc` (ID-token), `internal/pkg/auth0` (JWKS + audience/scope constants), and `internal/app/v3/bp/{context,cache}.go` (Business Partner enrichment, with cache).
3. **Handler adapter** — `internal/pkg/handler` (the `handler.Wrap` response/error envelope).
4. **Handler** — `internal/app/v4/usage/charts.go::Charts` (single function, dual-exposure).
5. **Domain / data** — not present in the slice; the sibling files `v4/usage/{billed,peercomparison}.go` and the v3 lineage at `internal/app/v3/ami/charts.go` strongly suggest an AMI/billing upstream.

### Notable Architectural Properties

- **Single handler, dual ingress.** `usage.Charts` must be agnostic to whether BP context arrived from the JWT path or the form path — the contract lives implicitly in the `bp` package’s context keys.
- **Path-parameter contract is uniform.** `{premises_id}` is a URL path parameter under both ingress modes; the M2M variant additionally requires `IAM_ID` via form data resolved by `bp.DetailsByFormMiddleware`.
- **Implicit deprecation marker.** Per the architect input, the parent `authenticated` group in `routes.go` carries a “remove 3 months after moving behind mulesoft” comment — the external variant is on a sunset path while the M2M variant is the forward-looking ingress.
- **Established test pattern.** Every non-trivial sibling handler (`charts`, `billed`, `districts`, `targets`, `submit`, `accounts`) has a paired `_test.go`, indicating an enforced test-with-feature convention.

## Quality & Risk

### Strengths
- **Test co-location is consistent.** `internal/app/v4/usage/charts_test.go` exists alongside the handler, and the convention holds across the v4 package — lowers the risk of untested regressions in this slice.
- **Auth concerns are factored out.** Scope/audience enforcement lives in reusable `basiciam` / `authc` middleware rather than inside the handler.
- **Clear v3 → v4 lineage.** The presence of `internal/app/v3/ami/charts.go` plus its tests gives reviewers a reference implementation when reasoning about behavioural deltas.

### Risks

1. **Divergent BP-context sources, shared handler.** The handler trusts context populated by either `bp.DetailsByJWTMiddleware` (JWT claims) or `bp.DetailsByFormMiddleware` (form-data). If the two middlewares ever drift in the keys/shape they write into `context.Context`, `usage.Charts` will silently degrade on whichever path was missed. There is no compile-time guarantee they stay in lockstep — `internal/app/v3/bp/context.go` is the choke point.
2. **Asymmetric outer middleware.** The external variant gets `downtime.Middleware()` and `middleware.LimitPayload(5MB)`; the M2M variant does not. During an outage window, the M2M ingress will continue serving while the external ingress is gated — intentional or not, this asymmetry is invisible to anyone reading only the handler.
3. **Authorization model relies on JWT audience-vs-scope distinctions.** External callers are gated by ID-token + (per `authc.Middleware`) a scope flag; M2M callers by audience `AudM2M` and `ScopeM2MReadChart`. There is no visible check inside the handler that the authenticated principal is actually entitled to the requested `premises_id` — this authorization is presumed to be enforced by `bp.Details*` middleware or downstream. Worth confirming in `charts.go`; if missing, it is a classic IDOR vector.
4. **Deprecation comment is a side-channel.** The “remove 3 months after Mulesoft” note lives in a comment on the parent group, not in a feature flag, header sunset, or telemetry hook. Easy to miss; risk of becoming stale and indefinitely live.
5. **Build/config blind spot.** The scan returned no `go.mod`, Dockerfile, or CI manifest, so we cannot verify Go version, dependency pins, or that this route is exposed correctly through the deployment ingress.
6. **5 MB payload limit on a GET endpoint.** `middleware.LimitPayload(5MB)` is applied to the group containing `r.Get(...)`. GETs should not be carrying bodies of that size; the limit is harmless but a hint that the group was sized for write-heavy siblings rather than this read endpoint.

## Recommended Next Steps

1. **Read `internal/app/v4/usage/charts.go` in full** and confirm:
   - Which BP-context keys it consumes, and whether it tolerates both `DetailsByJWT` and `DetailsByForm` producers.
   - Whether it enforces that the authenticated principal owns/serves the supplied `{premises_id}` (IDOR check).
2. **Audit `internal/app/v3/bp/context.go` + `cache.go`** to confirm the JWT and form middlewares write the same context keys and types. Add a typed accessor (e.g., `bp.FromContext(ctx) (Details, bool)`) if one doesn’t exist, so the handler depends on a single contract rather than a string key convention.
3. **Diff against `internal/app/v3/ami/charts.go`** to enumerate the v3 → v4 behavioural changes (response shape, query parameters, error semantics). This is the cheapest way to document the v4 contract for the engineering lead.
4. **Promote the deprecation marker out of comments.** Add a `Deprecation` / `Sunset` HTTP response header on the external variant, and emit a metric (`route=external_charts`) so the sunset window is measurable rather than aspirational.
5. **Normalize outer middleware between variants.** Either apply `downtime.Middleware()` to the M2M ingress as well, or document explicitly why M2M is exempt — currently the asymmetry is unmotivated by the code.
6. **Widen the scan to include `go.mod`, Dockerfile, and CI manifests** before sign-off, so dependency posture and deployment topology can be reviewed alongside the handler.
7. **Add a contract test** that exercises both ingress paths against a single fixture `premises_id` and asserts identical response bodies — this locks the “single handler, dual exposure” invariant in place before the external variant is removed.
