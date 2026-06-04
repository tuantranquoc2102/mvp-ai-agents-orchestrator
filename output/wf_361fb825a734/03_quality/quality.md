# Quality

_Agent: `reviewer` (Code Reviewer)_  
_Status: `success` · attempts: 1_

---

I was blocked from reading the handler source files (`internal/app/v4/usage/charts.go`, `charts_test.go`, `charts_response.go`, `errors.go`) — permission was denied. I'll proceed with the review based on the route registration that was supplied in the scan, the file inventory, and the structural signals available, and flag where I lacked source visibility.

---

# Code Review — `GET /v4/charts/{premises_id}`

## Scope reviewed
- **Route registration**: `internal/app/v4/routes.go:68` → `handler.Wrap(usage.Charts)`
- **Handler package**: `internal/app/v4/usage/` (charts.go, charts_response.go, errors.go, charts_test.go) — *source not readable in this session; assessment derived from surrounding wiring only*
- **Dual exposure**: same `usage.Charts` is also mounted at `/v4/user/charts/{premises_id}` under the M2M internal group with scope `ScopeM2MReadChart`
- **Touching models**: AMI meter & interval tables (elec/gas/water/smmu/demo), premises_configs, pilot_user, downtime_schedule
- **Migration**: `data/migrations/0005_.up.sql`

## Findings

### HIGH

1. **Same handler, two trust domains — verify authorization is uniform.** `usage.Charts` is registered on both the BP-JWT external route and the M2M internal route. The external path runs `bp.DetailsByJWTMiddleware()` (derives the caller's BP/account context from the user's JWT), while the M2M path runs `bp.DetailsByJWTMiddleware()`-equivalent context loading is **absent** from the visible internal block — only `ScopeM2MReadChart` is asserted. If `usage.Charts` relies on a BP-context value put into the request context by the middleware, the M2M path will either nil-deref or silently return data for the wrong premises. Confirm that (a) the handler explicitly authorizes the `{premises_id}` path param against the caller's allowed premises, and (b) the M2M path either injects equivalent context or the handler treats M2M differently. This is the single biggest risk on the surface area I can see.

2. **IDOR exposure on `{premises_id}`.** The path parameter is a direct object reference to consumption data. Without seeing the handler I cannot confirm, but any code path that fetches AMI intervals by `premises_id` without cross-checking that the authenticated principal owns/has access to that premises is a classic IDOR. Add an explicit ownership check (premises_id ∈ caller's BP-linked premises set) at the top of the handler, not deep in a repository call.

### MEDIUM

3. **Test coverage signal is thin.** Only `charts_test.go` exists alongside the handler. Charts logic that fans across three commodity tables (`ami_interval_elec`, `ami_interval_gas`, `ami_interval_water`), plus SMMU and demo variants, plus `premises_configs` and `pilot_user` gating, is a combinatorial surface. One test file usually cannot cover: (i) commodity-missing cases, (ii) demo vs. live meter routing, (iii) pilot-user-only paths, (iv) timezone/DST bucketing on intervals, (v) downtime/maintenance windows. Recommend table-driven tests per commodity + a "no data" and "partial data" case per commodity.

4. **Time-series endpoints are a known performance footgun.** AMI interval tables are typically very large. The handler should:
   - bound the query window server-side (reject or clamp absurd ranges from query params),
   - use covering indexes on `(premises_id, interval_ts)`,
   - stream/aggregate rather than load-all-then-marshal.
   Confirm a max-window guard exists; if not, this is a trivial DoS vector for an authenticated caller.

5. **Payload limit is global, not endpoint-specific.** `middleware.LimitPayload(5 << 20)` (5 MB) is set group-wide. For a GET chart endpoint the response size is the concern, not request size — verify a response-size or row-count cap on the SQL side.

6. **`downtime.Middleware()` at the external group only.** The M2M path bypasses downtime gating. If charts data is unavailable during maintenance, M2M consumers will get inconsistent/empty responses instead of the documented 503. Decide whether this is intentional.

### LOW

7. **Deprecated authenticated group still hosts a production endpoint.** The comment on `authenticated` says *"the function will be removed 3 months after moving behind mulesoft"*, yet `/v4/charts/{premises_id}` lives inside it. Either the deprecation note is stale or the chart endpoint needs a migration plan to the mulesoft-fronted path. Worth tracking.

8. **Route file imports `auth0` for M2M JWKS but external group uses `authc`.** Two auth stacks in one router is maintainable but easy to misconfigure. A short comment block describing which stack guards which route group would help future reviewers.

9. **Magic constant `5 << (10 * 2)`.** Readability nit — prefer `5 * 1024 * 1024` or a named constant `maxPayloadBytes`.

10. **Migration `0005_.up.sql` has no descriptive slug** in the filename. Future-you reading `git log` will not know what 0005 did without opening the file. Low priority; convention fix only.

## What I could not assess (blocked by file-read permissions)
- Input validation on `{premises_id}` and query params (date range, commodity selector).
- SQL construction — parameterized vs. string-built; any `fmt.Sprintf` into queries would be a SQL injection finding.
- Error handling — whether `errors.go` distinguishes 4xx vs. 5xx and avoids leaking DB errors to clients.
- Response shape and PII content of `charts_response.go`.
- Actual coverage in `charts_test.go`.

If you can grant read access to `internal/app/v4/usage/*.go`, I can convert items 1, 2, 4, and the "could not assess" list into concrete line-level findings.

## Priority summary
| Pri | Item | Action |
|---|---|---|
| H | Dual mount auth uniformity (#1) | Verify BP-context loading & scope checks on M2M path |
| H | IDOR on premises_id (#2) | Add explicit ownership check at handler entry |
| M | Test surface vs. commodity matrix (#3) | Add table-driven tests per commodity & edge case |
| M | Unbounded time window (#4) | Server-side clamp + index audit |
| M | Response-size cap (#5) | Add row/window limit |
| M | Downtime bypass on M2M (#6) | Decide & document |
| L | Deprecated group hosting live route (#7) | Migration plan |
| L | Dual auth stacks undocumented (#8) | Add comment |
| L | Magic constant (#9) | Named constant |
| L | Migration filename (#10) | Convention fix |
