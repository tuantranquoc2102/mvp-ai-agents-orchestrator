# Quality

_Agent: `reviewer` (Code Reviewer)_  
_Status: `success` · attempts: 1_

---

I do not have filesystem read permission to `F:\02_SPG_PROJECTS\jarvis-api`, and the `codebase_scan` payload was truncated at ~5.5 KB (the rest, ~584 KB, was cut). I can therefore only see the first portion of `internal/app/v4/routes.go` and the file inventory. I'll review what is visible and flag gaps where evidence is missing rather than speculate.

---

# Code Review — `/v4/charts/{premises_id}`

## What I could verify from the inputs

From `internal/app/v4/routes.go` (visible portion):
- The v4 router applies `downtime.Middleware()` and `middleware.LimitPayload(5 << (10 * 2))` (5 MB) at the `external` group.
- Authenticated routes go through `authc.Middleware(authc.Config{Scope: true, IDToken: true})`.
- A nested group inside `authenticatedRoutes` starts with `r.Use(bp.Details...)` (Business Premises details middleware) — strongly suggests `/v4/charts/{premises_id}` lives under this group and therefore inherits premises-detail context resolution.

From the file inventory:
- Handler: `internal/app/v4/usage/charts.go`
- Test: `internal/app/v4/usage/charts_test.go` (exists — good signal)
- Related siblings in the same package: `billed.go`, `peercomparison.go` (+ tests)
- The v3 ancestor (`internal/app/v3/ami/charts.go` + `_test.go`) is in scope, implying v4 likely wraps or migrates v3 logic.

## Findings

### HIGH

1. **Authorization on `{premises_id}` is not directly verifiable from the visible code.** The route exposes a premises-scoped resource via path parameter. The `bp.Details` middleware is the only line of defense visible. It is critical that this middleware enforces that the authenticated principal (from `authc`) is entitled to the `premises_id` in the URL — not merely that the premises exists. Without seeing `bp/middleware.go` and `charts.go`, I cannot confirm there's no IDOR (insecure direct object reference). **Action**: confirm `bp.Details` rejects requests where the caller's accounts/scopes don't include `premises_id`, and confirm `charts.go` does not re-read `premises_id` from the URL and bypass the middleware-resolved context.

2. **Truncated review surface.** I could not read `charts.go`, `charts_test.go`, or `bp/middleware.go`. Any sign-off on input validation, error handling, downstream call safety (SMRD/AMI), or context propagation is **not** something this review covers. A second pass with file contents is required before merge.

### MEDIUM

3. **Test coverage signal is positive but unmeasured.** `charts_test.go` exists, which is good. Without the file I cannot tell whether it covers:
   - Unauthorized caller / wrong-premises caller (authorization negative tests)
   - Invalid / malformed `premises_id`
   - Downstream timeouts and partial failures
   - Empty result sets vs. error responses
   Treat these as a checklist to confirm.

4. **Duplication risk with `v3/ami/charts.go` and `v3/ppms/charts.go`.** Three chart implementations across versions in scope (`v3/ami`, `v3/ppms`, `v4/usage`) suggest copy-paste evolution. Watch for divergent bug fixes — a fix landed in v3 may not be ported to v4. Recommend a shared internal package for chart aggregation logic if the response shapes overlap.

5. **Payload limit applied uniformly at 5 MB.** For a GET-style `/charts/{premises_id}` this is harmless inbound, but worth confirming the *response* path has its own bounds (time range / granularity caps) so a caller cannot request a multi-year, minute-level series that balloons memory or downstream cost.

### LOW

6. **Deprecation hygiene.** The visible file contains a `Deprecated:` comment on the `authenticated` function ("will be removed 3 months after moving behind mulesoft"). If `/v4/charts/{premises_id}` is registered inside the deprecated `authenticated` group rather than a non-deprecated successor, plan the migration alongside the mulesoft cutover so the endpoint doesn't disappear silently.

7. **Maintainability — middleware stacking.** The route depends on three layered middlewares (`downtime` → `authc` → `bp.Details`). Document this stack at the handler level (a comment in `charts.go`) so future authors don't add a sibling route outside the group and accidentally skip authorization.

8. **Observability not assessable.** I couldn't see whether the handler emits structured logs/metrics keyed by `premises_id` (with PII considerations) or just an opaque request id. For a charts endpoint that is performance-sensitive, confirm there is at least a latency histogram and an error counter labeled by failure class (auth / downstream / validation).

## What I need to actually finish this review

To convert the HIGH items from "unverified" to "cleared" or "blocking," I need read access — or pasted contents — of at minimum:
- `internal/app/v4/usage/charts.go`
- `internal/app/v4/usage/charts_test.go`
- `internal/app/v3/bp/middleware.go` and `internal/app/v3/bp/details.go`
- The exact route registration line for `/v4/charts/{premises_id}` in `internal/app/v4/routes.go` (it was past the truncation point)

Until then: **do not treat this as a clean review.** Treat it as a risk surface map.
