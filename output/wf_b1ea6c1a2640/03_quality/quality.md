# Quality

_Agent: `reviewer` (Code Reviewer)_  
_Status: `success` · attempts: 1_

---

I attempted to read the implementation files (`charts.go`, `charts_test.go`, related middleware) but the sandbox denied read permission on the project path. The only file content actually visible to me is `internal/app/v4/routes.go` from the `codebase_scan` input (other files appear in the truncated portion). I'll be explicit about which findings are evidenced and which are reasonable inferences from the route wiring.

# Code Review — `/v4/charts/{premises_id}`

## Scope confirmed
- **External route** (`routes.go:68`): `GET /v4/charts/{premises_id}` → `handler.Wrap(usage.Charts)` under JWT auth + BP-details middleware.
- **Internal M2M twin** (`routes.go`, internal group): `GET /v4/user/charts/{premises_id}` → same `usage.Charts`, but gated by `basiciam.RequireAccessToken`, audience claim, and `auth0.ScopeM2MReadChart`, using `bp.DetailsByFormMiddleware()` instead of JWT extraction.
- Implementation surface (per scan): `internal/app/v4/usage/charts.go` + `charts_response.go` + `errors.go`, with `charts_test.go` as the test file.

---

## Findings

### HIGH

1. **Same handler serves two trust boundaries with different identity-resolution paths.**
   `usage.Charts` is mounted on both the user-facing JWT route and the M2M `/v4/user/charts/{premises_id}` route. The external path resolves the BP context from the JWT (`bp.DetailsByJWTMiddleware`); the internal one resolves it from form data (`bp.DetailsByFormMiddleware`). That means the handler MUST treat `premises_id` as untrusted and verify it belongs to the resolved BP/account on **both** paths — otherwise the M2M caller (or a user supplying any premises id) gets an IDOR. I could not read `charts.go` to confirm this check is present; it's the single most important thing to verify. **Action:** confirm an explicit `premises_id ∈ accounts(BP)` authorization check inside `usage.Charts`, with a test that covers a foreign-premises request on each route.

2. **Test coverage signal is unverified.**
   `charts_test.go` exists in the scan list, but its scenarios were not visible. For a handler that fans out across two auth flavors, expected coverage is at minimum: (a) happy path JWT, (b) happy path M2M, (c) `premises_id` not owned by BP → 403/404, (d) downstream upstream-service failure → 5xx/translated error, (e) malformed/empty `premises_id`. **Action:** confirm these cases exist; if missing, prioritize (c) first.

### MEDIUM

3. **Deprecation/route hygiene drift.**
   `authenticated()` carries a `// Deprecated: ... 3 months after moving behind mulesoft` comment but is still actively registering charts and the rest of the v4 surface. There is no enforcement (no feature flag, no header gate, no metrics callout). **Action:** either drop the deprecation comment or add a sunset header / metric so the deprecation is observable; otherwise the comment rots and downstream consumers don't get the signal.

4. **Payload limit is set globally but `GET /v4/charts/{premises_id}` has no body.**
   `middleware.LimitPayload(5<<20)` on the external group is fine, but charts is GET-only — the more relevant safeguards (timeouts, per-request concurrency caps, response-size caps for chart payloads which can be large time-series) aren't visible here. **Action:** confirm there's an upstream timeout and that the chart response is paged or capped; chart endpoints are a classic OOM/latency hotspot.

5. **Duplicated routing for charts under different paths invites divergence.**
   `/v4/charts/{premises_id}` (user) and `/v4/user/charts/{premises_id}` (M2M) point to the same `usage.Charts`. If business rules diverge later (e.g., M2M needs to bypass a user-facing consent check, or a user gets PII redaction the M2M shouldn't), the shared handler will be edited for one and silently change the other. **Action:** either split into two thin wrappers around a service-layer function, or add an explicit `IsM2M` flag derived from middleware context with tests asserting both branches.

### LOW

6. **`/v4/pledge/status` mixed into the chart route group.**
   Not a charts concern directly, but it sits in the same authenticated block above charts with its own "Deprecated" comment and `// TODO - remove`. Keeping deprecated routes alongside actively maintained ones increases the chance of accidental middleware changes affecting both. Cosmetic, but worth a follow-up cleanup PR.

7. **Handler is registered via `handler.Wrap`** — fine, but error mapping and panic recovery are encapsulated there. Worth a one-line check that `handler.Wrap` recovers panics and emits structured logs with `premises_id` redacted (premises ids are identifiers that, while not PII alone, can be correlated). Not visible from this scan.

8. **No visible rate-limit middleware on the external authenticated group.** `downtime.Middleware()` and payload limit are present; per-user/per-IP throttling is not. For an endpoint returning time-series chart data, this is a cheap DoS vector. **Action:** confirm rate limiting exists at the gateway (Mulesoft) layer; if relying on it, document that the service has no in-process backstop.

---

## Verification checklist (to close gaps I couldn't inspect)

- [ ] Read `internal/app/v4/usage/charts.go` and confirm: (1) `premises_id` ownership check against BP context, (2) error wrapping in `errors.go` does not leak upstream detail, (3) context propagation with timeout.
- [ ] Read `charts_test.go` and verify the five test cases listed in Finding #2.
- [ ] Read `internal/app/v3/bp/context.go` to confirm `DetailsByJWTMiddleware` and `DetailsByFormMiddleware` produce the same context shape — the handler relies on this implicit contract.
- [ ] Confirm `handler.Wrap` panic recovery + structured logging behavior.

## Summary

Routing and middleware composition look correct in isolation, but the single highest risk is the **shared handler across user-JWT and M2M routes**: it must enforce premises ownership independently of which middleware populated the BP context. Without seeing `charts.go`, that's the finding I'd block a merge on until verified. Everything else (deprecation hygiene, rate-limit backstop, response-size caps) is improvement work rather than ship-blockers.
