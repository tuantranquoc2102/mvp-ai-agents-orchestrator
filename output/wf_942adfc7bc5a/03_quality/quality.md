# Quality

_Agent: `reviewer` (Code Reviewer)_  
_Status: `success` · attempts: 1_

---

I was unable to read the handler implementation files directly (permission denied) and the inline `codebase_scan` content was truncated after the v4 `routes.go` listing. The review below is therefore grounded in what is visible: the v4 routing/wiring for `/v4/charts/{premises_id}` plus the list of associated files in the scan. Implementation-level findings (auth-coupled bugs inside `usage.Charts`, query parsing, error mapping, etc.) could not be verified and are flagged as "unverified".

---

# Code Review — `GET /v4/charts/{premises_id}` (v4)

## Scope under review
- Route registration: `internal/app/v4/routes.go` (lines ~62–80, 95–112)
- Handler (declared but not readable): `internal/app/v4/usage/charts.go`
- Tests present: `internal/app/v4/usage/charts_test.go` (good signal — handler is covered)
- Surrounding middleware: `internal/app/v3/bp/context.go` (DetailsByJWTMiddleware, DetailsByFormMiddleware), `internal/app/v3/bp/cache.go`, `internal/app/v3/authc`, `internal/app/v3/downtime`

The endpoint is mounted twice:

| Surface | Path | Auth | BP details source |
|---|---|---|---|
| External (deprecated, JWT) | `/v4/charts/{premises_id}` | `authc.Middleware{Scope:true, IDToken:true}` | `bp.DetailsByJWTMiddleware()` |
| Internal M2M | `/v4/user/charts/{premises_id}` | `basiciam.RequireAccessToken` + audience `auth0.AudM2M` + scope `ScopeM2MReadChart` | `bp.DetailsByFormMiddleware()` |

---

## High priority

### H1. Two auth surfaces for the same handler — authorization must be re-checked inside `usage.Charts`
The same `usage.Charts` function is reached through:
- a user-context flow where the BP/account identity is derived from a **JWT** (`DetailsByJWTMiddleware`), and
- an M2M flow where the identity is supplied as **form data** (`DetailsByFormMiddleware`).

That means the `premises_id` URL parameter is **untrusted** and must be authorized against the BP details placed in the request context — otherwise an authenticated user with one BP can pull charts for any `premises_id` they can guess (IDOR). Please confirm the handler asserts `premises_id ∈ caller's premises set` and does not just trust the path. The M2M path is even more dangerous because the caller chooses the IAM ID via form input; without a strict ownership check, the M2M client effectively gets "read any chart". **Unverified — must inspect `usage.Charts`.**

### H2. M2M scope check is correct, but the external (JWT) route has no scope enforcement
The internal route gates with `basiciam.RequireClaimScope(auth0.ScopeM2MReadChart)`. The external route only requires "authenticated + IDToken" via `authc.Middleware`. If the JWT carries OAuth-style scopes (the `Scope:true` flag suggests so), the chart endpoint is currently accessible to any authenticated token regardless of scope. Either add a scope guard or document explicitly that the external route is open to all authenticated users.

### H3. Deprecation path is unclear
The comment above `authenticated` says *"will be removed 3 months after moving behind mulesoft"*, yet `/v4/charts/{premises_id}` is the only chart entry for mobile clients on this surface. There is no deprecation header, no telemetry tag on the route, and no sunset date in code. Risk: silent removal will break mobile. Add a `Deprecation`/`Sunset` response header (RFC 8594) and a metric counter so traffic can be observed before removal.

---

## Medium priority

### M1. 5MB payload limit on a GET endpoint
`r.Use(middleware.LimitPayload(5 << (10 * 2)))` is applied at the `external` group level. GETs shouldn't carry bodies, so 5MB is effectively a no-op here but is also surprisingly large for the rest of the group (which includes `POST /v4/smrd`). Not a defect for `/v4/charts` specifically, but worth confirming chart responses are not themselves unbounded — a long date range with high-resolution AMI data can balloon. Recommend an explicit cap on the date range / resolution at the handler.

### M2. Path param shape not validated at the router
`{premises_id}` is taken as-is. Recommend either a chi regex constraint (e.g. `{premises_id:[A-Z0-9]{6,20}}`) or an early-return validation in the handler to keep noisy 500s out of logs and to prevent cache-key pollution (see M3).

### M3. Cache key safety — verify `bp/cache.go` keys on caller identity, not just `premises_id`
The presence of `internal/app/v3/bp/cache.go` in the scan plus the BP-details middleware suggests a per-request cache. If the cache key is `premises_id` alone, then a stale entry from one tenant could be served to another. **Unverified — must inspect `bp/cache.go`.** If it does key off premises only and chart data is non-PII, fine; if it includes account info, the key must include the caller.

### M4. Test signal exists but coverage breadth is unknown
`charts_test.go` is present (good). Without being able to read it, please confirm tests cover at minimum:
- 200 happy path (with realistic AMI series)
- 401 when JWT missing / invalid
- 403 when `premises_id` doesn't belong to caller (the IDOR case from H1)
- 404 / empty when premises has no readings
- M2M scope failure (missing `ScopeM2MReadChart`)
- Time-range edge cases (DST boundary, future dates, zero-length range)
- Downstream timeout / 5xx propagation

The cluster of nearby `_test.go` files (`billed_test.go`, `peercomparison.go`, `context_test.go`, `submit_test.go`) suggests the package has a testing convention — apply the same to `charts_test.go` if not already.

### M5. Handler wrapped via `handler.Wrap` — confirm panic recovery + structured errors
The pattern `handler.Wrap(usage.Charts)` typically returns `(payload, error)` and centralizes JSON serialization. Verify that:
- Panics inside `usage.Charts` (e.g. nil-deref on missing BP details) produce a 500 rather than crashing the server.
- Domain errors (premises not found, no entitlement, upstream AMI 5xx) map to distinct HTTP statuses, not all 500.

**Unverified — must inspect `internal/pkg/handler/handler.go`.**

---

## Low priority

### L1. Duplicate route registration — DRY
`/v4/charts/{premises_id}` (external) and `/v4/user/charts/{premises_id}` (internal) both wire to `usage.Charts`. Consider extracting a small `chartsRoute(r chi.Router)` helper so future changes (rate limiting, caching headers, observability) are applied in one place rather than two.

### L2. Inconsistent grouping comment
`// Routes without details` precedes `POST /v4/pledge/status` and is then followed by `// Details-required routes` containing the charts handler. The comment block is fine, but the deprecated pledge route sitting in the same `authenticated` function as still-current chart traffic makes the file harder to bisect. Move the deprecated route into its own group or file.

### L3. No response caching headers visible in route wiring
Chart data is usually safe to cache at the edge for minutes. Consider `Cache-Control: private, max-age=…` set inside the handler — at the router level it's invisible, which makes ops debugging harder.

### L4. Logging / tracing not visible at this layer
No `r.Use(...)` for request ID / tracing in the v4 external group. If the project standard is to put it at the top-level Router (above `v4.Router`), ignore — otherwise add it so `/v4/charts/{premises_id}` errors are correlatable.

---

## What I could not verify (please re-run the review with these files readable)
1. `internal/app/v4/usage/charts.go` — for H1, H2, M1, M5 (authorization, scope, payload size, error mapping).
2. `internal/app/v4/usage/charts_test.go` — for M4 (coverage breadth).
3. `internal/app/v3/bp/context.go` and `internal/app/v3/bp/cache.go` — for M3 (cache key composition) and H1 (what `DetailsByJWTMiddleware` actually places in the context, and whether it cross-checks `premises_id`).
4. `internal/pkg/handler/handler.go` — for M5 (panic recovery, error mapping contract).

The file-read tool was blocked by permissions and the inline scan content was truncated after `v4/routes.go`. If you re-run with the four files above expanded, I can convert H1/H2/M3/M5 from "unverified" to confirmed findings or clear them.
