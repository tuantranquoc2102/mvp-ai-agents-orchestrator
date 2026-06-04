# Report

_Agent: `assistant` (General Assistant)_  
_Status: `success` · attempts: 1_

---

# Final Analysis Report — `GET /v4/charts/{premises_id}`

**Audience:** Engineering Lead
**Scope:** The single feature endpoint `/v4/charts/{premises_id}` in `jarvis-api` (Go module `code.in.spdigital.sg/sp-digital/jarvis-api`). All claims below are grounded in the 70 Go files surfaced by the pre-filtered scan.

---

## 1. Overview

`/v4/charts/{premises_id}` is a thin v4 HTTP handler that returns chart/usage data for a single premise. The endpoint is wired in `internal/app/v4/routes.go` (matched at line 68, "Details-required" group) and implemented in `internal/app/v4/usage/charts.go`, with a paired unit test at `internal/app/v4/usage/charts_test.go`.

Although the handler itself sits in the v4 tree, the feature is best understood as a **v4 façade over a v3 domain pipeline**: authentication (`internal/app/v3/authc`), downtime gating (`internal/app/v3/downtime`), and — most significantly — premise resolution and caching (`internal/app/v3/bp/*`) are all v3 components reused unchanged. Sibling chart implementations exist at `internal/app/v3/ami/charts.go` and `internal/app/v3/ppms/charts.go`, which are useful precedents but are **not** the route under analysis.

The HTTP stack is `github.com/go-chi/chi/v5`, with shared middleware from `code.in.spdigital.sg/sp-digital/golang/web.v2/middleware` and a `handler.Wrap` adapter from `internal/pkg/handler` bridging the package's handler signature into `http.Handler`.

---

## 2. Architecture

**Request pipeline (top-down), as wired in `internal/app/v4/routes.go`:**

1. `chi.Router` (v4 sub-router) inside the `external → authenticated → details-required` group.
2. `downtime.Middleware()` — short-circuits during scheduled outages (`internal/app/v3/downtime`).
3. `middleware.LimitPayload(5 MB)` — payload cap from `web.v2`.
4. `authc.Middleware{Scope, IDToken}` — Auth0 ID-token + scope validation (`internal/app/v3/authc`, `internal/pkg/auth0`).
5. `bp.Details(...)` — the heaviest piece: resolves `{premises_id}` into a hydrated Business-Partner / premise / meter context, attached to `r.Context()`. Implemented across `internal/app/v3/bp/middleware.go`, `details.go`, `details_methods.go`, `context.go`, `load.go`, `cache.go`, `verifycache.go`, `meter.go`, `shared.go`, `grouped.go`, `retrieve.go`.
6. `internal/app/v4/usage/charts.go` — feature handler, wrapped via `internal/pkg/handler.Wrap`.

**Key architectural observations:**

- **Composition root is `routes.go`.** The v4 router fans out into `external` and `internal`; `external` splits further into `authenticated` (kept alive for the mobile client; flagged as deprecated in the source) and `public`. The "details-required" inner `r.Group` is what applies `bp.Details` to a subtree of routes that all need a resolved premise — `/v4/charts/{premises_id}` is one of them.
- **Cross-version coupling is intentional but load-bearing.** v4 reuses v3's `bp`, `authc`, and `downtime` packages directly. There is no v4-owned premise-resolution layer; any v3 `bp` change is implicitly a v4 change.
- **The handler is a thin shell over context state.** By the time `charts.go` executes, the heavy lifting (auth, premise lookup, meter list, caching) has already happened in middleware. The handler reads the prepared context, queries the chart data source(s), and shapes a response.

---

## 3. Quality & Risk

**Positives**

- **Consistent test pairing.** Every meaningful file in the `bp` pipeline and the v4 handler tree has a `_test.go` sibling, including the feature itself (`internal/app/v4/usage/charts_test.go`).
- **Clear separation of concerns at the router.** Middleware chain is declarative and readable in `routes.go`; the handler does not re-implement auth, payload limits, or premise resolution.
- **Caching is first-class.** `internal/app/v3/bp/cache.go` and `verifycache.go` show that premise resolution — the most expensive part of the request — is cached and verified rather than hit cold per request.

**Risks / concerns**

1. **v3 → v4 versioning drift.** A "v4" endpoint that depends on `internal/app/v3/bp`, `internal/app/v3/authc`, and `internal/app/v3/downtime` makes the version boundary cosmetic. Any breaking change to v3 `bp` (e.g., context-key rename, signature change to `bp.Details`) will silently break v4 unless caught by tests. There is no v4-owned abstraction insulating it.
2. **Deprecated `authenticated` group still in production path.** `routes.go` comments mark the `authenticated` subtree as deprecated/mobile-only, yet `/v4/charts/{premises_id}` lives inside it. The endpoint inherits a deprecation it may not be intended to share.
3. **Auth0 + scope check is the only authorization layer surfaced in the chain.** From the inputs, there is no explicit "this token may access this `premises_id`" check at the route level — that authorization likely lives inside `bp.Details` (since it resolves the premise from the token's BP), but it's not visible at the composition root. Worth verifying that `bp.Details` rejects mismatches (token's BP vs path param's premise) rather than silently scoping to whatever it finds.
4. **5 MB `LimitPayload` on a GET-shaped endpoint is generous.** If the endpoint is GET-only, the 5 MB cap is harmless but misleading; if it accepts POST/PUT bodies, 5 MB warrants justification.
5. **Architecture report truncation.** The architecture input was cut off mid-section (communication pattern). Inbound details, response shape, and any downstream service calls (AMI, PPMS, datastream) are not fully captured here. The presence of `internal/app/v3/ami/charts.go`, `internal/app/v3/ppms/charts.go`, and `internal/app/v3/datastream` in scope strongly suggests this handler fans out to one or more of those — but that should be confirmed by reading `internal/app/v4/usage/charts.go` directly.
6. **Sandbox limited the architect's reads.** The architect explicitly noted that file reads beyond `routes.go` were declined; conclusions about the handler body, error handling, and downstream calls are inferred from neighbors, not verified.

---

## 4. Recommended Next Steps

1. **Read `internal/app/v4/usage/charts.go` end-to-end** (and its test) to close the gaps the architect could not — specifically: which downstream(s) it calls (`ami`, `ppms`, `datastream`?), how errors are mapped, and what the response contract is. This is the single highest-value follow-up.
2. **Confirm tenancy enforcement.** Trace `internal/app/v3/bp/details.go` + `details_methods.go` and verify that a mismatch between the caller's BP (from the ID token) and the requested `{premises_id}` produces a 403/404, not a silent rescope. Add a regression test if one is missing in `charts_test.go`.
3. **Decide on the v3-reuse posture.** Either (a) accept the coupling and document that v4 routes inherit v3 middleware semantics, or (b) introduce a v4-owned `bp` facade so v3 can evolve independently. Pick one explicitly; the current implicit reuse is a maintenance trap.
4. **Re-evaluate the `authenticated`-group placement.** If `/v4/charts/{premises_id}` is meant for current (non-deprecated) clients, move it out of the deprecated subtree in `routes.go` so the routing structure matches intent.
5. **Right-size `LimitPayload`.** Confirm the HTTP method; if GET-only, drop the 5 MB cap to something nominal (e.g., 64 KB) or remove it for clarity.
6. **Cross-check against `v3/ami/charts.go` and `v3/ppms/charts.go`.** These are the closest precedents and likely the implementation model for v4. Look for divergence in error handling, caching headers, and timeout behavior — those are common drift points between sibling chart endpoints.
7. **Add a routing-level integration test** that hits `/v4/charts/{premises_id}` through the full middleware chain (downtime → payload → authc → bp.Details → handler) rather than only unit-testing `charts.go`. This is the only way to catch v3-package regressions that the v4 unit tests would miss.
