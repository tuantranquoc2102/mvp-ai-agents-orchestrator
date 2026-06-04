# Architecture

_Agent: `architect` (Software Architect)_  
_Status: `success` · attempts: 1_

---

# Architecture Analysis — `GET /v4/charts/{premises_id}`

Drawing on the pre-filtered file list and the embedded content of `internal/app/v4/routes.go`, this is what the feature looks like structurally. (File reads beyond the embedded snippet were declined by the sandbox, so claims below are scoped to evidence present in the inputs.)

## 1. Layering (top-down)

```
HTTP edge (chi v5)
  └─ internal/app/v4/routes.go              ← composition root for v4
       ├─ Cross-cutting middleware
       │    ├─ downtime.Middleware()                  (internal/app/v3/downtime)
       │    ├─ web.v2/middleware.LimitPayload(5MB)    (external SDK)
       │    ├─ authc.Middleware{Scope, IDToken}       (internal/app/v3/authc → auth0)
       │    └─ bp.Details(...)                        (internal/app/v3/bp)
       └─ Feature handler
            └─ internal/app/v4/usage/charts.go        ← /v4/charts/{premises_id}
                 wrapped via internal/pkg/handler.Wrap
```

The `Router` function fans out into `external` and `internal` groups, then `external` further splits into `authenticated` (deprecated path, kept for the mobile client) and `public`. Inside `authenticated`, a nested `r.Group` applies `bp.Details` before registering "details-required" routes — `/v4/charts/{premises_id}` lives in that subtree.

## 2. Modules touched by this feature

| Layer | Package | Role for this endpoint |
|---|---|---|
| Routing | `internal/app/v4` | Registers the route, wires middleware chain |
| Handler | `internal/app/v4/usage` (`charts.go`, `charts_test.go`) | Owns request parsing, validation, response shaping for `/v4/charts/{premises_id}` |
| Authn/Authz | `internal/app/v3/authc`, `internal/pkg/auth0` | Validates ID token + scope from Auth0 (legacy path; v4 reuses v3) |
| Domain context | `internal/app/v3/bp` (`middleware.go`, `details.go`, `context.go`, `cache.go`, `verifycache.go`, `load.go`, `meter.go`, `shared.go`) | Resolves the `premises_id` path param into a fully hydrated Business Partner / premise context (with caching) attached to `r.Context()` |
| Reliability | `internal/app/v3/downtime` | Short-circuits requests during scheduled outages |
| Handler glue | `internal/pkg/handler` | `Wrap()` adapter — converts the package's handler signature into `http.Handler` |
| External SDK | `code.in.spdigital.sg/sp-digital/golang/web.v2/middleware`, `chi/v5`, `basiciam` | Framework primitives |

## 3. Communication pattern

- **Inbound**: synchronous HTTP `GET` via chi, path-param `{premises_id}`.
- **In-process orchestration**: middleware → handler via `context.Context` value-passing. `bp.Details` loads premise/meter data once and stashes it on the context so `usage.Charts` doesn't re-query; the `cache.go` / `verifycache.go` pair indicates this is memoised (likely Redis or in-proc) and validated per request.
- **Outbound** (inferred from package names, not directly read): the BP loader calls downstream meter/account services; the actual chart data fetch in `usage/charts.go` will hit AMI/SMRD-style upstream — the sibling `v3/ami/charts.go` and `v3/ppms/charts.go` files in the scan suggest charts in v4 are a façade over the v3 AMI client.

## 4. Versioning & reuse pattern

v4 is **not** a clean rewrite — it is an additive overlay on v3:

- `internal/app/v4/routes.go` imports `v3/authc`, `v3/bp`, `v3/downtime` directly.
- Only the *handler* moves to `v4/usage`; the auth, premise-context, and downtime machinery stay in `v3/*` and are shared across v1–v5 routers.
- This is the standard "share infrastructure, fork the handler" pattern for API versioning. Acceptable, but see smells below.

## 5. Structural smells

1. **Cross-version coupling that pretends to be a version boundary.** `v4` depending on `v3/authc`, `v3/bp`, `v3/downtime` means the `vN` directory is *not* a true version boundary — it's just a handler namespace. Any breaking change to `v3/bp.Details` silently changes v4 (and v5) behaviour. Consider promoting the shared middleware to a version-neutral package (e.g. `internal/pkg/premise`, `internal/pkg/authc`) so the `vN` packages contain only handlers and route wiring.
2. **`bp` is a god package.** The scan shows 17+ files in `internal/app/v3/bp` (`details`, `grouped`, `load`, `cache`, `verifycache`, `context`, `middleware`, `meter`, `shared`, `removecache`, `retrieve`, …). It owns middleware, caching, domain loading, HTTP context plumbing, and shared helpers. This is a candidate for split into `bp/middleware`, `bp/cache`, `bp/loader`, `bp/context` sub-packages.
3. **Deprecated comment on `authenticated` group.** Routes.go explicitly marks the `authenticated` group as deprecated ("will be removed 3 months after moving behind mulesoft"), yet `/v4/charts/{premises_id}` is wired through it. The endpoint inherits a known sunset path; the migration plan for moving it to the mulesoft-fronted group should be tracked.
4. **`handler.Wrap` indirection.** Using a custom wrapper instead of `http.HandlerFunc` is fine, but it hides the handler's true signature from chi's typing — worth confirming that the wrapper centralises error mapping/observability so individual handlers don't duplicate it.
5. **Tests are co-located but cross-cut.** `v4/usage/charts_test.go` exists, but the feature also exercises `v3/bp/*` heavily. Hermetic handler tests must mock `bp.Details`; integration tests of the full chain are not visible in the scan.
6. **No cyclic-import evidence in scope.** Within the listed files I see no `v3 → v4` imports (v4 → v3 only), so no package cycle for this feature. Worth re-checking if any `v3/bp` file imports anything under `v4`.

## 6. Open questions to resolve before implementation work

- Does `usage/charts.go` consume the AMI client directly, or does it route through a `v3/ami` adapter? (sibling `v3/ami/charts.go` is in the scan but its relationship to v4 usage charts is not visible from imports here.)
- Is `bp.Details`'s cache layer in-process or distributed? `cache.go` + `verifycache.go` + `removecache.go` strongly imply distributed (Redis), but evidence is not in the embedded content.
- Authorisation rule: `authc.Middleware` enforces `Scope` and `IDToken` — is there an additional check that the authenticated principal *owns* `{premises_id}`, or is that inside `bp.Details`? This is the security pivot point for the endpoint and should be confirmed in `bp/middleware.go` / `bp/details.go`.
