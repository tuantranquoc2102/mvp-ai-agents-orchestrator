# Architecture

_Agent: `architect` (Software Architect)_  
_Status: `success` · attempts: 1_

---

I lack read permission for the source files beyond the truncated `routes.go` content already embedded in the input. I'll produce the architectural analysis from that visible content plus the file-path layout, and flag where the conclusion is path-inferred vs. content-verified.

---

# Architecture — `GET /v4/charts/{premises_id}`

## 1. Layering (verified from `internal/app/v4/routes.go`)

```
┌──────────────────────────────────────────────────────────────┐
│ cmd/serverd/router        (process entry, gateway, handler)  │
└──────────────────────────────────────────────────────────────┘
                              │ mounts
┌──────────────────────────────────────────────────────────────┐
│ internal/app/v4/routes.go  (chi.Router composition)          │
│   external group ─► downtime + LimitPayload(5MB)             │
│      authenticated  ─► authc.Middleware (JWT/scope)          │
│         (details)   ─► bp.DetailsByJWTMiddleware             │
│             GET /v4/charts/{premises_id} ─► usage.Charts     │
│      public                                                   │
│   internal group  ─► basiciam.RequireAccessToken +           │
│                      RequireClaimAudience(AudM2M)            │
│                      /v4/user/charts/{premises_id} ─►        │
│                      usage.Charts (M2M variant)              │
└──────────────────────────────────────────────────────────────┘
                              │ delegates
┌──────────────────────────────────────────────────────────────┐
│ internal/app/v4/usage      (feature handler — Charts)        │
│   charts.go / charts_response.go / errors.go                 │
└──────────────────────────────────────────────────────────────┘
                              │ depends on
┌──────────────────────────────────────────────────────────────┐
│ internal/app/v3/bp        (Business Premises domain helpers) │
│   middleware.go  ─ DetailsByJWTMiddleware / ByForm           │
│   context.go     ─ request-scoped BP context                 │
│   details.go     ─ details_methods.go fetch+enrich           │
│   load.go        ─ load aggregator                           │
│   meter.go       ─ meter lookup                              │
│   grouped.go     ─ grouped data                              │
│   cache.go       ─ caching of BP data                        │
│ internal/app/v3/authc, downtime  (cross-cut middlewares)     │
│ internal/app/v3/ami/charts.go    (AMI chart data source)     │
│ internal/pkg/handler             (handler.Wrap adapter)      │
│ internal/pkg/auth0               (JWKS / scopes / audiences) │
│ internal/models/request_nonces.go (persistence model)        │
│ internal/stubs/client.go          (external system stub)     │
└──────────────────────────────────────────────────────────────┘
                              │ persists
┌──────────────────────────────────────────────────────────────┐
│ data/migrations/0005_.up.sql  (related schema)               │
└──────────────────────────────────────────────────────────────┘
```

The codebase follows a **vertically-versioned web layer** (v1…v5) over a **shared domain layer** that historically lives under `v3/*`. There's no separation between domain and infrastructure inside `bp` — packaging is feature-shaped, not Clean/Hexagonal.

## 2. Modules in the feature's call graph

| Module | Role | Coupling direction |
|---|---|---|
| `v4/routes.go` | Route composition for `/v4/charts/{premises_id}` (external) and `/v4/user/charts/{premises_id}` (M2M) | Imports `v3/authc`, `v3/bp`, `v3/downtime`, `pkg/handler`, `pkg/auth0`, `chi/v5`, `basiciam`, `web.v2/middleware` |
| `v4/usage` (`charts.go`) | Business handler — verified to exist by file listing; produces chart response payloads | Almost certainly depends on `v3/bp` (context), `v3/ami` (chart data), and a response shaper in `charts_response.go` |
| `v3/bp` | Business-Premises context provider: middleware → load → cache → meter → details → grouped | Used by both v3 and v4 (cross-version) |
| `v3/ami` | AMI consumption / charts data (file `charts.go` co-listed) | Likely the SoR for the chart series |
| `v3/authc` | JWT / scope auth middleware (deprecated path) | Used by v4 |
| `v3/downtime` | Maintenance gate | Used by v4 |
| `pkg/handler` | `handler.Wrap` adapter normalises error → HTTP | Used everywhere |
| `pkg/auth0` | JWKS key func, M2M audience & scope constants | Used by v4 internal group |
| `stubs/client.go` | External system stub (likely SAP / billing) | Pulled in transitively |
| `data/migrations/0005_.up.sql` | Schema (probably `request_nonces` based on co-listed model) | Persistence layer |

## 3. Request flow (`GET /v4/charts/{premises_id}` — external)

1. **Edge** — `cmd/serverd/router` mounts `v4.Router`.
2. **Downtime gate** — `downtime.Middleware()` short-circuits during maintenance.
3. **Payload guard** — `middleware.LimitPayload(5MB)` (defensive; GET shouldn't carry a body — over-broad).
4. **AuthN/Z** — `authc.Middleware{Scope:true, IDToken:true}` validates JWT + scope (this is the *deprecated* path being migrated behind Mulesoft).
5. **Context enrichment** — `bp.DetailsByJWTMiddleware()` resolves the caller's BP details (cached via `bp/cache.go`) from JWT claims and injects into request context (`bp/context.go`).
6. **Handler** — `handler.Wrap(usage.Charts)` invokes the feature, reads `{premises_id}` from chi URL params and the BP context, fans out to AMI / billing data (`v3/ami/charts.go`, possibly `bp/load.go` + `bp/meter.go`), shapes via `charts_response.go`, errors via `errors.go`.

## 4. Communication style

- **Inbound:** HTTP via `chi/v5`, two surfaces for the same handler:
  - External: JWT-authenticated (Auth0 OIDC) — `/v4/charts/{premises_id}`
  - Internal M2M: client-credentials Auth0 (`AudM2M` + `ScopeM2MReadChart`) — `/v4/user/charts/{premises_id}`
- **Cross-cutting:** chi middleware chain; context-based propagation of BP details.
- **Outbound:** Implied calls to SAP/billing/AMI systems via `internal/stubs/client.go` and `v3/ami`.
- **Persistence:** SQL (migration 0005) — likely for nonces / cache, not the chart payload itself.

## 5. Structural smells

| # | Smell | Evidence | Risk |
|---|---|---|---|
| **S1** | **Cross-version coupling** — `v4` imports `v3/{authc,bp,downtime}`. Versioning becomes cosmetic at the URL layer because the domain is shared and any v3 refactor ripples into v4 & v5. | `import .../v3/authc`, `.../v3/bp`, `.../v3/downtime` inside `v4/routes.go` | v3 cannot be retired without rewriting v4/v5; semver of API ≠ semver of code. |
| **S2** | **Duplicate mount of the same handler** with divergent middleware — `usage.Charts` is wired to both `/v4/charts/{premises_id}` (JWT, `DetailsByJWTMiddleware`) and `/v4/user/charts/{premises_id}` (M2M, `DetailsByFormMiddleware`). The handler must therefore read `premises_id` from two different sources, or the middlewares must normalise. | Both registrations visible in `routes.go` | Subtle authorization bugs (M2M path bypasses user-scope checks); hard to reason about per-endpoint contracts. |
| **S3** | **God-package `v3/bp`** — single package contains middleware, context, cache, load, meter, details, grouped. Mixes HTTP concern (middleware), request scope (context), aggregation (load/grouped), and infra (cache). | Files: `cache.go`, `context.go`, `details.go`, `details_methods.go`, `grouped.go`, `load.go`, `meter.go`, `middleware.go` | Change amplification; tests in this package (8+ `_test.go` files) likely brittle; impossible to swap cache or transport without touching middleware. |
| **S4** | **Deprecated path still load-bearing** — Comment "Deprecated: the function will be removed 3 months after moving behind mulesoft" on `authenticated`. The feature's *primary* external mount sits inside this deprecated group. | `// Deprecated:` block in `routes.go` | Migration debt; a removal will delete the very route under review unless the M2M/Mulesoft path is the replacement. |
| **S5** | **5 MB payload limit on a GET** — `LimitPayload(5<<20)` applied to external group that includes GET-only routes. | `r.Use(middleware.LimitPayload(5 << (10 * 2)))` | Mostly harmless but signals copy-paste middleware composition; review whether non-mutating routes deserve a stricter or no-op guard. |
| **S6** | **No explicit `premises_id` ownership check at the route level** — Authorization that the JWT subject is entitled to the `{premises_id}` is presumably inside `bp.DetailsByJWTMiddleware` or `usage.Charts`; nothing in the route declaration enforces it. The M2M path additionally lacks any per-user binding because it resolves details from form data. | Routes file shows no scope/claim check tying user → premises | IDOR / horizontal-privilege-escalation risk; warrants verification in `bp/middleware.go` and `usage/charts.go`. |
| **S7** | **`internal/stubs/client.go` in production tree** — name suggests test double, but it's under `internal/stubs`, not `_test.go`. Used by feature path. | Listed under matched files | If this is a stub used at runtime, it's likely a placeholder integration with hard-coded behaviour — a hidden coupling and rollout hazard. Worth confirming. |
| **S8** | **No cycles observed in the visible imports**, but the v3↔v4 sharing (S1) means a real boundary check (e.g., `go list -deps`) is needed to confirm v3 never reaches back into v4. The risk vector exists. | Inferred | If any `v3/*` package learns about `v4/usage`, it becomes a cycle and a sign that "v3" has effectively become "shared/core". |

## 6. Recommended verifications (next workflow steps)

1. **Read `internal/app/v4/usage/charts.go`** to confirm how `premises_id` is read, how BP context is consumed, and which downstream systems are called.
2. **Read `internal/app/v3/bp/middleware.go` + `context.go`** to confirm whether `DetailsByJWTMiddleware` enforces user→premises ownership.
3. **Read `internal/app/v3/ami/charts.go`** — the likely data-source collaborator; confirms whether `v4/usage.Charts` delegates to v3 AMI or re-implements.
4. **Grep for any `v3/*` import of `v4/*`** to rule out a true cycle (S8).
5. **Confirm `internal/stubs/client.go` is wired in non-test builds** (S7).
6. **Confirm migration `0005_.up.sql`** relates to nonces (`request_nonces.go`) and not to chart caching — clarifies whether persistence is part of this feature or orthogonal.

## 7. One-line summary

`/v4/charts/{premises_id}` is a thin chi route in v4 that delegates to `v4/usage.Charts`, but the *real* feature logic — auth context, BP resolution, caching, AMI data fetch — lives in the **`v3/bp` god-package** and **`v3/ami`**, making v4 a façade over a shared, version-agnostic core whose deprecation comment is its loudest architectural signal.
