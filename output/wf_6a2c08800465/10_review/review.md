# Review

_Agent: `reviewer` (Code Reviewer)_  
_Status: `success` · attempts: 1_

---

# Final Review — Risk List (Highest First)

## 1. **The rationale doc was never actually written — only 107 bytes hit disk**
The `write_rationale` tool reports `bytes_written: 107` while the architect's own summary says the write was *blocked pending permission* and the body shown is a multi-section document that cannot fit in 107 bytes. Either (a) a stub/placeholder was written and the real content was dropped, or (b) the tool lied. **Block merge until the file on disk is opened and verified to contain §1–§5 + verification gates.** Without this, downstream reviewers have no rationale artifact to sign off against.

## 2. **Neither agent has read access to the target repos**
The architect explicitly states "the SA and I lack read access to `F:\02_SPG_PROJECTS\...`." Every concrete path, package name, class name, and config key in the plan is therefore an *assumption* labelled `(verify)`. The plan is structurally sound but not yet grounded in the actual codebase. **No "logic-parity checklist" can be completed without reading `jarvis-api` source.** The plan must not be executed until at least one agent has confirmed file access and re-grounded the inventory.

## 3. **Datasource divergence is gated but the gate has no owner or escalation path**
The plan says "Hard gate — do not proceed if datasources diverge without sign-off" but does not name *who* signs off, what artifact captures the decision, or what the fallback is if `jarvis-api` reads from a schema `skalbox-api` cannot reach. If Jarvis uses a separate DB/credentials/replica, this migration is not a port — it's a cross-database integration, and the scope changes materially.

## 4. **No parity test for time-zone and rounding behavior**
The rationale flags time-zone and rounding parity as open questions, but the test plan only mentions byte-identical Postman responses and snapshot fixtures. Snapshots captured at a single wall-clock instant will not catch:
- DST boundary differences if the Jarvis JVM ran in a different TZ
- `BigDecimal` rounding mode / scale differences
- Locale-dependent month boundaries (week-of-month, ISO vs. US)
Add property-based or parameterized tests across at least: month boundaries (Jan/Dec, Feb leap year), DST transitions, and zero/negative/large-value rounding cases.

## 5. **"Byte-identical (modulo whitespace/ordering)" is not a real assertion**
The contract regression test says responses must be byte-identical *modulo ordering*. JSON field ordering, null vs. missing field, empty-array vs. null array, and number formatting (`1.0` vs `1` vs `1.00`) are exactly the kind of silent contract breaks this migration is likely to introduce. Specify the comparison rule explicitly (e.g. JSONassert STRICT vs LENIENT, or a documented canonicalizer) and pin it in CI.

## 6. **Shared Jarvis client / other callers not audited**
Rationale lists "shared Jarvis client" as an open question. Before deleting `JarvisClient`, the plan must grep skalbox-api for all references — not just the `/monthly` path. If other endpoints share the client class, retry config, or circuit breaker, deletion will break them. The plan currently treats client removal as a clean drop.

## 7. **No rollback / feature-flag strategy**
The migration replaces a remote call with in-process logic in one commit. If parity drifts in production, the only rollback is a revert + redeploy. A feature flag (`monthly.source=local|jarvis`) that routes between the new in-process path and the existing client for one release cycle would let prod traffic validate parity safely. Not mentioned anywhere.

## 8. **Jarvis-api decommissioning is out of scope but not tracked**
Rationale puts "jarvis-api decommissioning" out of scope, which is fine — but there is no follow-up ticket, no deprecation header on the Jarvis endpoint, and no traffic-monitoring plan to confirm skalbox-api stops calling it. Risk: the Jarvis endpoint lingers indefinitely as dead code that still appears live in dashboards.

## 9. **Observability parity is asserted but not specified**
Cross-cutting logging is listed as a change, and observability appears in the parity checklist, but there is no enumeration of: existing metric names, log MDC keys, trace span names, or alert rules tied to the Jarvis-side `/monthly`. If skalbox-api emits different metric names, dashboards and alerts break silently post-migration.

## 10. **Caching semantics under `@Cacheable` may change cardinality**
The plan says "port the cache region + config" but cache keys derived from `JarvisClient` argument shapes won't match keys derived from the new internal service signatures. Cold-cache load on cutover could spike DB read load. Needs an explicit cache-key audit and a warm-up or staged rollout.

## 11. **AuthN/AuthZ parity is in the checklist but not in the test plan**
The parity table includes authn/z as a row, but the test plan does not include negative-auth tests (missing token, expired token, wrong scope/role). If Jarvis enforced auth at its boundary and skalbox-api previously relied on that, in-process logic may now run under a different security context.

## 12. **Error-payload mapping preservation is asserted but not pinned**
"Preserve current `@ControllerAdvice` behavior" is stated, but no test pins the exact error JSON shape, error codes, or HTTP status for each failure mode. Clients often parse error payloads — this is a contract surface that must be locked with fixtures, same as the success path.

## 13. **Postman collection as a regression artifact is fragile**
Postman collections drift, are not run in CI by default, and rarely cover error cases. Treating the Postman collection as the contract source-of-truth is weaker than a committed JSON-schema or contract test (Spring REST Docs / Pact). At minimum, the Postman run must be wired into CI with assertions, not just executed manually.

## 14. **Branch slug/path appears truncated**
The rationale filename `2026-06-08-migrate-endpoint-monthly-logic-from-jarvis-api-i.md` ends with `-i` — looks truncated mid-word ("into-skalbox-api"?). Cosmetic, but suggests the slug was generated without a length check and may collide or mislead in `git log`.

## 15. **"Each step independently buildable" is claimed, not proven**
Step 0 captures baselines; subsequent steps presumably add the in-process service, then delete the client. The plan summary is truncated, but if entity/repo porting and client deletion land in the same commit, the branch will not be bisectable. Confirm step granularity preserves green builds after each commit, and that deletion of `JarvisClient` is the *last* step, gated on parity tests passing.

---

**Recommended gate before execution:** resolve #1, #2, and #3 first — without the rationale on disk, repo access, and a datasource decision, the remaining risks cannot even be properly evaluated.
