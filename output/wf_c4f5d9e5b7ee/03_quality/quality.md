# Quality

_Agent: `reviewer` (Code Reviewer)_  
_Status: `success` · attempts: 1_

---

I'm working with what's available in the input scan (most file contents were truncated at ~263KB cut-off, and direct filesystem reads are blocked outside the working directory). The review below is based on the visible route wiring, the file inventory, and the test-file presence signals — wherever I couldn't read source directly I flag the finding as needing handler-level verification.

---

# Code Review — `/v4/charts/{premises_id}`

## Scope confirmation
Two endpoints actually wire `usage.Charts` (same handler, two contracts):

| Path | Auth | Premises source | Middleware |
|---|---|---|---|
| `GET /v4/charts/{premises_id}` | End-user JWT (IDToken + Scope) | `bp.DetailsByJWTMiddleware` (JWT-derived) | `downtime`, `LimitPayload(5MB)`, `authc.Middleware{Scope,IDToken}`, BP-by-JWT |
| `GET /v4/user/charts/{premises_id}` | M2M OAuth2 (Auth0) | `bp.DetailsByFormMiddleware` (form-data) | `RequireAccessToken`, `RequireClaimAudience(AudM2M)`, BP-by-Form, `RequireClaimScope(ScopeM2MReadChart)` |

Reusing one handler across two trust boundaries is the most important structural fact about this feature.

---

## High-priority findings

### H1. Confused-deputy / IDOR risk on the JWT-authenticated route — needs handler verification
On `/v4/charts/{premises_id}` the **URL path param** carries `premises_id`, but the middleware (`bp.DetailsByJWTMiddleware`) also resolves the caller's BP/premises from the JWT and puts it in `context`. If `usage.Charts` reads `premises_id` from the URL and queries against it *without* cross-checking it belongs to the JWT-derived BP, any authenticated user can fetch any other user's chart by guessing/scraping IDs. The same risk exists on the M2M route, but it's lower because callers are server-side and already gated by `ScopeM2MReadChart`.
- **Action**: confirm `usage.Charts` either (a) ignores the URL param and uses the context BP, or (b) asserts the URL param is in the JWT-derived premises set, and return 403 otherwise. This must have an explicit test (negative case where URL id ≠ JWT id).

### H2. `bp.DetailsByFormMiddleware` on a `GET` endpoint
The M2M route is `GET` but the middleware reads identity from form data. `application/x-www-form-urlencoded` on GET is non-standard and many proxies/clients won't forward bodies on GET — this is usually a sign the middleware actually parses query params, but the name says "Form". This is fragile: if a future caller switches HTTP libraries (or the middleware is later strict-parsed), the M2M endpoint silently 4xx's, or worse, falls through with an empty premises identity. Verify what `DetailsByFormMiddleware` actually parses and that it rejects missing/blank `iam_id` rather than defaulting.

### H3. Two trust boundaries, one handler — implicit coupling
`usage.Charts` is consumed by both authenticated end-users and M2M clients with different identity-resolution shapes. Any future change (e.g. adding rate-limiting keyed on user, adding a per-call audit log, switching from path param to body) silently affects both consumers. Without an architectural seam this becomes a refactor hazard.
- **Action**: at minimum, document the contract in a comment over `usage.Charts`. Better: split into `usage.ChartsForUser` and `usage.ChartsForM2M` that both call a shared `service.GetCharts(ctx, bp, opts)` so middleware-derived context is the only input the core function sees.

---

## Medium-priority findings

### M1. `LimitPayload(5 << (10*2))` (5 MB) on a `GET`
GETs don't have meaningful bodies. A 5 MB cap here is dead config and also misleading — it suggests an upload limit that doesn't apply. Either move `LimitPayload` to the route groups that actually take bodies, or set it to a small value (e.g. 4 KB) for the GET group so a malicious large GET body is rejected at the edge.

### M2. Test coverage is present but unverifiable in depth
`internal/app/v4/usage/charts_test.go` exists, and the v3 BP middleware has good test breadth (`details_methods_test.go`, `grouped_test.go`, `load_test.go`, `middleware_test.go`, `context_test.go`, `meter_test.go`). What I cannot verify from the inventory:
- Is there a negative-path test asserting **403/404 when `premises_id` in the URL is not owned by the JWT subject**? (H1.)
- Is there a test covering the **M2M-with-missing-scope** path returning 403?
- Is there a test where `DetailsByFormMiddleware` receives **no `iam_id`** at all?
- Is there a test for **downtime middleware short-circuiting** the chart endpoint?
- Is there an integration/router-level test that asserts the v4 route is mounted under the correct middleware stack (not just the handler in isolation)?

These are the four tests I would require before merging changes to this surface.

### M3. Versioning / deprecation hygiene
`v4/routes.go` carries a `Deprecated: the function will be removed 3 months after moving behind mulesoft` comment on `authenticated`. The `/v4/charts/{premises_id}` endpoint sits inside that deprecated group. There's no visible date, ticket, or feature flag tying the deletion to a milestone. This is the kind of "deprecation that never happens" — pin it to an issue and a date or remove the comment.

### M4. Cross-version dependency
`v4/routes.go` imports `internal/app/v3/bp` and `internal/app/v3/authc`. v4 cannot be evolved or removed independently of v3 internals. For a chart endpoint this is workable, but the boundary should be a thin shared package (e.g. `internal/pkg/bp`) rather than v3 owning code that v4 depends on. Otherwise v3 retirement breaks v4 silently.

---

## Low-priority findings

### L1. Route literal duplication
`r.Get("/v4/charts/{premises_id}", handler.Wrap(usage.Charts))` and `Get("/charts/{premises_id}", handler.Wrap(usage.Charts))` inside `r.Route("/v4/user", …)` both ultimately serve charts. The path-param name is identical, the handler is identical, but the prefixes diverge. Consider extracting a `const chartsByPremisesPath = "/charts/{premises_id}"` and composing.

### L2. `handler.Wrap` is the only thing translating handler returns to HTTP responses
All routes go through `handler.Wrap`. Error mapping, status codes, and panic recovery for the chart endpoint are entirely determined there — any silent change in `handler.Wrap` affects this feature's contract. Worth one comment-level link from `usage.Charts` documenting the contract it relies on.

### L3. Public chart-adjacent routes
Sibling routes `/v4/public/greengoals/charts/district` and `/v4/public/greengoals/charts/country` exist under `public` (no auth). They are not the same feature, but if a developer mistakenly registers a future chart-like endpoint there, they bypass all of the above auth. Naming convention (`/v4/public/...` for unauthenticated) is the only safeguard. Cheap improvement: a linter/test that fails if `chart` or `usage` appears in the `public` group.

---

## Priority summary (what I'd block on)

| # | Severity | Issue | Required before merge? |
|---|---|---|---|
| H1 | High | URL `premises_id` vs JWT-derived BP must be reconciled with a deny test | **Yes** |
| H2 | High | Verify `DetailsByFormMiddleware` parses correctly on `GET` and rejects empty IAM ID | **Yes** |
| H3 | High | Handler reused across user-JWT and M2M trust boundaries — needs documented contract or split | Recommended |
| M1 | Med | 5 MB `LimitPayload` on a GET-only group is misleading | No, but easy fix |
| M2 | Med | Add the 4 negative tests listed above | **Yes** |
| M3 | Med | Pin the `Deprecated` comment to a date/ticket | No |
| M4 | Med | v4 → v3 internal-package dependency | No |
| L1–L3 | Low | Polish / future-proofing | No |

**Net assessment**: structure and middleware are reasonable, test scaffolding around BP details is healthy, but the feature has a classic dual-trust-boundary handler and an unverifiable IDOR question on the URL path param. Those two (H1 + M2 negative tests) are the gating items.
