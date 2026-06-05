# Quality

_Agent: `reviewer` (Code Reviewer)_  
_Status: `success` · attempts: 1_

---

I attempted to read the feature files directly but file-system access was not granted in this session. The `codebase_scan` payload also truncated the `content` field of `TrailController.java` (the primary `/monthly` file) around the area of interest. The review below is therefore based on the visible portion of the scan (imports, class signature, annotations, sibling endpoints, file inventory) plus inferences from the related files listed. Anything I could not verify from source is flagged as **unverified**.

---

# Code Review — `/monthly` Feature

## Scope as observed
- Primary entry point: `TrailController` (`/ubm/trail`), with `/monthly` referenced at lines 103 and 126 (per scan).
- Supporting layers: `ChartService` / `ChartServiceImpl`, DTOs `MDHChart`, `BillExplainer`, `ChartApiException`, and chart controllers (`ChartController`, `PrivateChartController`).
- Tests present for chart, account, payment, refund, profilextractor, SMRD, auth services, and `ChartControllerTest` — so the feature lives inside a module that has some existing test scaffolding.

## High-priority findings

**H1. Could not directly inspect the `/monthly` handler body — verify a few specific things.**
The truncated content stops before line 103. Before merging, confirm that the `/monthly` endpoint(s):
- Apply `@SkalboxM2MSecured(scopes = "read:spd.skalbox.trails")` (or the chart-specific scope) consistently — the sibling endpoints in the visible portion do, but a missing annotation here would silently expose the route.
- Validate `accountNo` against the authenticated principal/tenant. Sibling endpoints accept `accountNo` as a free-form `@RequestParam`; if `/monthly` follows the same pattern without a server-side ownership check, it is an **IDOR risk** (any M2M caller with the scope can read any account's monthly data).
- Constrain date range (max window) on any CSV variant — `CSV_MONTHLY` is imported, so a CSV stream likely exists. Unbounded ranges over `Flux<ResponseCsv>` are a DoS footgun.

**H2. CSV streaming endpoints lack visible back-pressure / size caps.**
The visible `downloadPubConcessions` returns `Flux<ResponseCsv>` with no `produces = "text/csv"`, no row cap, no timeout. If the `/monthly` CSV mirrors this shape, the same applies. Recommendation: enforce a max date span, add `produces = MediaType.TEXT_CSV` (or `text/csv`), and add a `.timeout(...)` / `.take(maxRows)` guard. **Unverified for `/monthly` specifically — confirm against the real handler.**

## Medium-priority findings

**M1. Authorization model relies solely on scope, not on resource ownership.**
`@SkalboxM2MSecured(scopes = "read:spd.skalbox.trails")` is coarse-grained. Across this controller, *any* client with the scope appears to read *any* `accountNo`. For an M2M-only surface this may be acceptable, but it should be an explicit, documented decision and ideally enforced by a downstream service check rather than implied by scope.

**M2. Parameter validation is implicit.**
Visible endpoints use `@RequestParam(defaultValue = "DESC") String direction` with no `@Pattern` / enum binding, and `pageSize` is an unbounded `Integer`. A caller passing `pageSize=1000000` will be accepted at the controller layer. Apply `@Min/@Max` and an enum for `direction`. Likely the same shape in `/monthly`.

**M3. Test coverage signal is mixed.**
`ChartControllerTest` and `ChartServiceImplTest` exist, which is good — but there is **no `TrailControllerTest`** in the file inventory even though `/monthly` lives on `TrailController`. If the new endpoint was added here, it appears untested at the controller layer. Add WebFlux slice tests covering: happy path, missing scope (401/403), invalid date range, and oversized page size.

**M4. Reactive/blocking boundary is invisible from here.**
`ChartServiceImpl` is reachable from `TrailController` (reactive) and from `ChartController` (likely reactive as well). Confirm `ChartServiceImpl` doesn't do blocking JDBC / blocking HTTP without `.subscribeOn(Schedulers.boundedElastic())`. Mixing blocking work onto Netty event-loop threads is a recurring footgun in WebFlux apps and won't show up until load.

## Low-priority findings

**L1. Constant naming.** `CSV_MONTHLY` is fine, but if there is also a non-CSV `/monthly`, prefer two distinct constants (`ROUTE_MONTHLY`, `ROUTE_MONTHLY_CSV`) and keep them in `ChartConstants` rather than letting raw string literals leak into the controller.

**L2. Tab-vs-space indentation.** The visible file uses tabs while the surrounding Spring conventions (and most of the listed test files) typically use 4 spaces. Worth normalizing via Spotless/`google-java-format` if not already enforced.

**L3. `@Loggable` on every endpoint.** Fine if the annotation redacts PII; verify it does not log full request bodies / `accountNo` to non-restricted log sinks.

---

## What I need to finalize this review
- Lines 95–140 of `TrailController.java` (the actual `/monthly` handler[s]).
- The `ChartService.getMonthly...` / matching method in `ChartServiceImpl` to confirm threading + validation.
- Whether a `TrailControllerTest` exists (the scan suggests not).

If you can re-run the scan without truncation, or grant read access to those specific files, I can convert H1/H2 from "verify" into concrete confirmed findings.
