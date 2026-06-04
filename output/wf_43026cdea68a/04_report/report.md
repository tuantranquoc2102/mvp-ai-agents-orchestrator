# Report

_Agent: `assistant` (General Assistant)_  
_Status: `success` · attempts: 1_

---

# Final Analysis Report — `GET /v4/charts/{premises_id}`

## Overview

`/v4/charts/{premises_id}` is the v4 incarnation of the premises usage/chart endpoint in the `jarvis-api` service (module `code.in.spdigital.sg/sp-digital/jarvis-api`). The endpoint is mounted in `internal/app/v4/routes.go` (line 68) under the authenticated, details-required route group, and is served by the handler in `internal/app/v4/usage/charts.go` (paired with `charts_test.go`). Despite living in the v4 package, the feature is *not* self-contained: it depends materially on `internal/app/v3/bp/*` for premises resolution/caching and almost certainly delegates the actual time-series shaping to `internal/app/v3/ami/charts.go` and `charts_response.go`. In effect, v4 is a thin transport/orchestration wrapper that re-exports a v3 capability behind a refined route surface.

The scope footprint in the inventory is small (a single handler file + test, plus shared v3 plumbing), but the *blast radius* is large because the v3 BP and AMI packages are shared with v3 routes still in production.

## Architecture

**Request pipeline** (top to bottom, as composed in `internal/app/v4/routes.go`):

1. `chi.Router` (`github.com/go-chi/chi/v5`) — version-scoped `Router(r chi.Router)`.
2. `downtime.Middleware()` from `internal/app/v3/downtime` — global kill-switch / maintenance gate.
3. `middleware.LimitPayload(5 << 20)` from `code.in.spdigital.sg/sp-digital/golang/web.v2/middleware` — 5 MB request cap (defensive only; GET endpoint).
4. `authc.Middleware{Scope: true, IDToken: true}` from `internal/app/v3/authc` — Auth0-backed JWT validation requiring both an access scope and an ID token (uses `internal/pkg/auth0`).
5. `bp.DetailsByJWTMiddleware()` from `internal/app/v3/bp/middleware.go` — resolves the JWT subject + `{premises_id}` URL param into a populated Billing-Premises (BP) context attached to the request. Hits `bp/cache.go` / `verifycache.go` on the hot path; `removecache.go` is the invalidation seam.
6. `handler.Wrap(...)` from `internal/pkg/handler` — standard response/error envelope adapter.
7. Handler: the function in `internal/app/v4/usage/charts.go`.

**Layering for this endpoint:**

| Layer | Files |
|---|---|
| Transport / routing | `internal/app/v4/routes.go` |
| Cross-cutting middleware | `v3/downtime`, `web.v2/middleware`, `v3/authc`, `v3/bp/middleware.go` + `details_methods.go` |
| Handler | `internal/app/v4/usage/charts.go` |
| Shared domain (premises) | `internal/app/v3/bp/{details,details_methods,retrieve,load,sort,meter,enrolment,grouped,getbpdetails,shared,context,cache,verifycache,removecache}.go` |
| Shared domain (charts) | `internal/app/v3/ami/{charts,charts_response,bdl,emds,srlpmech,download}.go` |
| Infra glue | `internal/pkg/handler`, `internal/pkg/auth0` |

**Notable architectural properties:**

- **Versioned-by-folder API.** Each `internal/app/v{N}/routes.go` is its own router; v4 is additive, not a rewrite. The endpoint reuses v3 internals directly rather than going through an internal interface — coupling is by Go import, not by contract.
- **Pre-resolution via middleware.** The handler does not parse `{premises_id}` itself; `bp.DetailsByJWTMiddleware` does, and stuffs the resolved BP into request context. This keeps the handler simple but hides an I/O + cache lookup behind every call.
- **Auth is dual-factor at the token level** (scope *and* IDToken required), which is stricter than typical bearer-only endpoints in the same router.

## Quality & Risk

**Coupling / boundary risks**
- The "v4" label is mostly cosmetic. `v4/usage/charts.go` reaches into `v3/bp` and (almost certainly) `v3/ami`. Any change to the v3 BP/AMI types — sort order in `v3/bp/sort.go`, response shape in `v3/ami/charts_response.go`, cache key shape in `v3/bp/cache.go` — silently changes v4's contract. There is no anti-corruption layer between the version boundaries.
- Because `v3/bp` is shared with the still-live v3 routes, a defect found via `/v4/charts/{premises_id}` cannot be fixed in isolation.

**Caching surface**
- The presence of `cache.go`, `verifycache.go`, and a separate `removecache.go` in `v3/bp` is a smell worth confirming: three files implying read / validate / invalidate suggests cache coherence has already bitten the team. Every chart request flows through this layer via the JWT middleware, so cache misses or stale BP data show up as latency or wrong-tenant data on this endpoint.

**Auth posture**
- Requiring both `Scope` and `IDToken` is good (defense in depth). Worth verifying the middleware fails closed if either is malformed, and that scope claims are checked against this specific endpoint rather than a coarse "authenticated" bucket.

**Payload limit**
- `LimitPayload(5 << 20)` is applied uniformly. For a GET chart endpoint this is essentially inert; the limit exists for sibling POSTs in the same group. Not a defect, but it means the endpoint inherits no per-route rate-limiting or response-size guarding from what's visible in `routes.go`.

**Testing**
- Only `internal/app/v4/usage/charts_test.go` is in scope for v4. Coverage of the middleware chain (`bp.DetailsByJWTMiddleware`, `authc.Middleware`) for this specific route is not visible — those are tested, if at all, in their owning packages, which means there is likely no integration test exercising the full `/v4/charts/{premises_id}` pipeline end-to-end.

**Observability**
- Nothing in the scoped inventory indicates per-route metrics, tracing spans, or structured logging at the handler boundary. `handler.Wrap` may provide some of this, but it is not confirmed by the scoped files.

**Determinism / response stability**
- `v3/bp/sort.go` and `v3/bp/grouped.go` imply ordering logic outside the handler. If chart output depends on BP iteration order, a refactor to either file can change response payloads without touching anything in `v4/`.

## Recommended Next Steps

1. **Read & summarize `internal/app/v4/usage/charts.go`.** The single highest-value action — the architecture above is inferred from the route registration and neighbouring files; the handler body will confirm whether it delegates to `v3/ami/charts.go`, what query params it accepts, and what it returns.
2. **Confirm the v3/ami dependency.** Grep `v4/usage/charts.go` for imports of `v3/ami`. If present, document the exact functions called and treat `v3/ami/charts_response.go` as part of the v4 public contract.
3. **Introduce an anti-corruption seam.** Define a small interface in `v4/usage` (e.g. `chartProvider`) that `v3/ami` satisfies, so v4 can evolve (or be tested with fakes) without importing v3 internals directly.
4. **Add a full-pipeline test.** A handler-level test in `charts_test.go` that exercises `authc` + `bp.DetailsByJWTMiddleware` + handler against an in-memory cache. Today's `charts_test.go` likely stubs the middleware, which leaves the integration untested.
5. **Audit the BP cache trio.** Read `v3/bp/cache.go`, `verifycache.go`, `removecache.go` together and document the invalidation contract. If any chart-data freshness bug is ever reported on `/v4/charts/{premises_id}`, this is the first place to look — make that easier now.
6. **Verify scope enforcement.** Check what scope `authc.Middleware{Scope: true}` actually requires for this route group in `v4/routes.go`. If it's a generic "authenticated" scope, tighten it to a charts/usage-specific scope so token compromise has a smaller blast radius.
7. **Decide v4's purpose.** If v4 is intended to eventually replace v3, schedule the migration of `v3/ami/charts*` and `v3/bp/*` into `v4/` (or a neutral `internal/domain/` package). If v4 is only a routing facade, document that explicitly in `v4/routes.go` so future contributors don't add business logic there.
8. **Add per-route observability.** Wrap the handler with a tracing span named `v4.charts.get` and emit a metric tagged by `premises_id` cardinality bucket (not the raw ID) — this endpoint is on the user hot path and currently has no visible instrumentation in the scoped files.
