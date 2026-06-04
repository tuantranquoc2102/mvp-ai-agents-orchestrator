# Report

_Agent: `assistant` (General Assistant)_  
_Status: `success` · attempts: 1_

---

# Final Analysis — `GET /v4/charts/{premises_id}`

## Overview

The endpoint exposes premises-level chart/usage data for the v4 public API of `jarvis-api` (Go service, chi router). It is registered at a single site, `internal/app/v4/routes.go:68`, and is served by the `usage.Charts` handler in `internal/app/v4/usage`. A second, machine-to-machine twin is mounted in the same router at `/v4/user/charts/{premises_id}` and reuses the same `usage.Charts` function — the only differences are the credential layer (Auth0 ID token vs. SP Digital `basiciam` client-credentials with audience `AudM2M` and scope `ScopeM2MReadChart`) and how premises context is resolved (`bp.DetailsByJWTMiddleware` vs. `bp.DetailsByFormMiddleware`).

Feature surface in scope: 30 files / ~327 KB, almost entirely Go, plus one SQL migration (`data/migrations/0005_.up.sql`). The handler depends heavily on the shared Business Partner (`internal/app/v3/bp/`) package for premises/account/meter resolution and caching, and is a likely descendant of the v3 AMI charts implementation (`internal/app/v3/ami/charts.go`, `download.go`).

## Architecture

**Routing & middleware composition (verified from `internal/app/v4/routes.go`):**

```
cmd/serverd/router/{gateway.go,handler.go}
   └─ internal/app/v4/routes.go
        external group ─► downtime.Middleware → middleware.LimitPayload(5MB)
            authenticatedRoutes ─► authc.Middleware{Scope:true, IDToken:true}
                detailsRequired  ─► bp.DetailsByJWTMiddleware
                    GET /v4/charts/{premises_id}  →  handler.Wrap(usage.Charts)
            internalRoutes (M2M) ─► basiciam.RequireAccessToken
                                    + RequireClaimAudience(AudM2M)
                                    + bp.DetailsByFormMiddleware
                    /v4/user/charts/{premises_id} → handler.Wrap(usage.Charts)
```

**Layering:**
- **Transport / composition** — `cmd/serverd/router/gateway.go` mounts v1→v5 onto chi; only `v4.Router` owns this exact path.
- **Edge** — `downtime` + `LimitPayload(5MB)` are applied uniformly to the external surface; an `authc` JWT/scope gate sits inside that.
- **Identity context** — the `bp` package (`internal/app/v3/bp/`) is the de-facto identity-context layer: `middleware.go` provides both JWT and form-based resolvers; `details.go` / `details_methods.go` resolve account/premises; `load.go`, `grouped.go`, `meter.go` provide premises+meter lookups; `cache.go` memoizes details; `context.go` plumbs the request-scoped value.
- **Feature handler** — `internal/app/v4/usage` (`charts.go`, `charts_response.go`, `errors.go`) implements the response contract via the shared `handler.Wrap` adapter (`internal/pkg/handler`).
- **Downstream / data** — `internal/stubs/client.go` is the downstream client surface; `internal/models/request_nonces.go` and `data/migrations/0005_.up.sql` are the only feature-scoped data artifacts (idempotency/nonce tracking).

**Cross-cutting observations:**
- The v4 handler reuses v3 `bp` middleware verbatim rather than introducing a v4-specific identity layer — economical, but it couples v4 to v3 lifecycle.
- The dual public/M2M registration of the same handler is a deliberate share-the-business-logic pattern; differences are confined to middleware wiring.

## Quality & Risk

**Strengths**
- Single registration site (`routes.go:68`) — the surface is easy to reason about and audit.
- Auth posture is layered and explicit: outage gate → payload cap → JWT/scope → premises-context binding, with M2M held to a distinct audience+scope (`AudM2M`, `ScopeM2MReadChart`).
- Pre-existing test scaffolding around the feature: `charts_test.go`, `download_test.go`, plus BP-layer tests (`details_methods_test.go`, `grouped_test.go`, `load_test.go`, `context_test.go`, `middleware_test.go`, `meter_test.go`) and `retrieve_average_bill_test.go`. The middleware chain the handler depends on is well-covered.

**Risks / unknowns**
1. **`usage.Charts` body was not in the pre-filtered bundle.** Every conclusion about request/response shape, downstream fan-out, error mapping, and timeout/retry behavior is currently inferred from siblings (`v3/ami/charts.go`, `download.go`). This is the single biggest blind spot before sign-off.
2. **Shared handler, divergent auth assumptions.** Because `usage.Charts` serves both an end-user (Auth0 ID token, premises from JWT) and an M2M caller (premises from form), the handler must not implicitly trust JWT-derived identity fields. Worth confirming in code that `premises_id` and any account scoping are always read from the `bp` context produced by whichever resolver ran, not from raw JWT claims.
3. **`bp` package is v3-owned.** A v4 endpoint depending on `internal/app/v3/bp/...` means any v3 deprecation or refactor is a v4 breakage vector. There is no v4 abstraction wrapping it.
4. **Migration `0005_.up.sql` is the only data artifact in scope** and its content was not surfaced — it should be confirmed to be the table backing the chart data path (and reviewed for indexes on `premises_id` / time-range columns, which dominate chart-query cost).
5. **`handler.Wrap` error contract is unverified.** Whether `usage/errors.go` maps domain errors to consistent HTTP statuses (404 unknown premises, 403 cross-tenant, 502 downstream) needs to be checked against `internal/pkg/handler`.
6. **Payload cap is on the request (5MB) but no explicit response-size or query-range cap is visible from the routing layer.** Chart endpoints commonly need a server-side bound on time-window size; confirm one exists in the handler.

## Recommended Next Steps

1. **Pull and review the missing sources** before any further architectural call:
   - `internal/app/v4/usage/charts.go`, `charts_response.go`, `errors.go`
   - `internal/pkg/handler` (the `Wrap` adapter and error contract)
   - `internal/pkg/authc` and `internal/pkg/downtime` (to document the auth + outage contract precisely)
   - `data/migrations/0005_.up.sql` (confirm schema + indexing on `premises_id` and any time column)
2. **Verify identity-source discipline in `usage.Charts`**: premises and account IDs must come from `bp.Context`, never from JWT claims directly — this is what keeps the M2M and end-user paths safe behind one function.
3. **Audit the v3→v4 coupling.** Decide whether `bp` should be promoted to a version-neutral package (`internal/pkg/bp`) or whether v4 should own a thin adapter. Today, a v3 cleanup will land on a v4 endpoint.
4. **Confirm bounded inputs.** Check that `usage.Charts` enforces a maximum time window / resolution server-side; if not, add one and a test.
5. **Backfill targeted tests for the v4 handler.** The `bp` layer is well-tested; mirror that depth at the v4 entry — at minimum: happy path, unknown premises, cross-tenant premises, downstream timeout, oversized range, and parity tests proving the public and M2M routes produce identical responses for equivalent inputs.
6. **Document the dual mount.** A short note in `internal/app/v4/usage` (or the route comment in `routes.go`) stating that `/v4/charts/{premises_id}` and `/v4/user/charts/{premises_id}` share a handler — with the two middleware contracts spelled out — will prevent a future change from silently breaking one path.
7. **Add an explicit observability check.** Confirm the handler emits a span/log line carrying `premises_id`, caller type (user vs. M2M), and downstream latency; if missing, add it before the next release — chart endpoints are common latency offenders and the dual-auth shape makes attribution important.
