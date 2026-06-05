# Quality

_Agent: `reviewer` (Code Reviewer)_  
_Status: `success` · attempts: 1_

---

I attempted to read the source files for full review but the read permissions weren't granted. The input JSON included file contents but was truncated at the test file. Based on the visible signals (file inventory, partial `ChartControllerTest.java`, project structure), here is a scoped review of the `ChartController` feature.

---

# Code Review — `ChartController` Feature

## Scope reviewed
- **Controllers (prod):** `ChartController.java`, `PrivateChartController.java`
- **Service:** `ChartService.java`, `ChartServiceImpl.java`
- **Scheduler:** `TariffScheduler.java`
- **DTO:** `BDLChart.java`
- **Tests:** `ChartControllerTest.java` (partial content visible), `PrivateChartControllerTest.java`, `ChartServiceImplTest.java`
- **Adjacent (in scan but out-of-feature):** Redis repositories, `UserService`, `SkalboxSecured` annotation

> ⚠️ **Reviewer limitation:** Only `ChartControllerTest.java` content was visible (truncated at ~115k chars remaining). Findings on the production controllers, service, and scheduler are inferred from naming, structure, and test interactions. A second pass with full source access is recommended before merging.

---

## Findings

### 🔴 HIGH

1. **Reactive `Mono` error propagation — verify negative paths are covered end-to-end.**
   `ChartControllerTest#tesMonthly_Fail` (note the typo `tes`) sets up `Mono.error(new ChartApiException(...))` but only the first line is visible. Reactive controllers commonly leak generic 500s when `ChartApiException` isn't mapped via a `@ControllerAdvice`/`WebExceptionHandler`. **Action:** confirm there is a global exception handler that maps `ChartApiException` to a sanitized HTTP response, and that the test calls `.expectError(ChartApiException.class)` rather than just asserting type without consuming the signal. Also verify that exception messages from upstream (Jarvis/SAP/BDL) are not echoed verbatim to clients — they often contain internal IDs or stack hints.

2. **Two controllers in the same feature (`ChartController` + `PrivateChartController`) — confirm auth boundary.**
   Splitting into public/private surfaces is a known footgun: it's easy for a handler intended to be private to be accidentally registered on the public router, or for the `SkalboxSecured` annotation to be applied unevenly. **Action:** verify (a) every `PrivateChartController` endpoint is annotated with `@SkalboxSecured` (or whatever the project's auth gate is), (b) `ChartController` endpoints that take user-scoped inputs (`ebsPremiseNo`, `accountNos`) enforce that the authenticated user owns those premises/accounts — IDOR is the obvious risk here.

### 🟡 MEDIUM

3. **`@SpringBootTest(classes = { ChartController.class })` is heavier than needed.**
   The test uses `@SpringBootTest` but mocks every collaborator (`ChartService`, `TariffScheduler`, `SAPService`, `TariffRepositoryImpl`, `ServerWebExchange`). This is effectively a unit test wearing a Spring context. Switching to a plain JUnit + Mockito test (or `@WebFluxTest`) would cut test runtime substantially across the suite. Not a correctness bug, but a maintainability/CI-cost smell.

4. **Mocking `ServerWebExchange` is a brittleness signal.**
   `@MockitoBean ServerWebExchange exchange` is then passed straight through to the service. If the controller is doing nothing with the exchange except forwarding it, the parameter is effectively pass-through plumbing — fine, but if the controller ever needs to read headers/principal from it, the mock will give NPEs on any new code path. Consider whether the controller should extract just what it needs (e.g., authenticated principal) and pass a typed value to the service.

5. **Test data is hardcoded with shape-specific magic strings (`"P1"`, `"2021"`, `"2021-12"`, `"ACC1"`).**
   Acceptable for unit tests, but `consumptionValue("2021")` next to `month("2021-12")` suggests the API mixes "year" and "year-month" semantics across endpoints. Worth confirming the DTOs validate format (e.g., `@Pattern`) — otherwise a malformed input becomes a downstream parse error or, worse, a silent wrong-period query.

6. **Typo in test name: `tesMonthly_Fail`.**
   Cosmetic but it propagates to CI reports and grep. Easy fix.

7. **`BillExplainer.SK.Request` builder line ends with a stray `;` on its own line.**
   ```java
   billExplainerReq = ...build();
   ;
   ```
   Harmless but indicates the file hasn't been through a formatter. Run `spotless`/IDE format on the test package.

### 🟢 LOW

8. **`@MockitoBean` (Spring Boot 3.4+) is used — good.** Modern API, no `@MockBean` deprecation debt. Keep this consistent across the test base.

9. **`StepVerifier` usage on success path is correct** (`assertNext(...).verifyComplete()`). Make sure the failure tests use `expectError(ChartApiException.class).verify()` rather than `verifyComplete()` (can't tell from the truncation).

10. **`BDLChart.Daily.Request.getDailyRequestForGraph(dailySKRequest)` — static factory on a DTO.**
    Static converters on DTOs are fine but tend to grow into untested mapping logic. If `BDLChart` doesn't have its own unit tests, the mapping is implicitly tested only via controller tests, which won't catch field-by-field regressions. Recommend a dedicated mapper test if the BDL request shape is non-trivial.

11. **`TariffScheduler` is in scope but only appears as a `@MockitoBean` here.** Schedulers triggered by `@Scheduled` are a common source of "works in test, fires twice in prod" bugs (multi-instance deployments without `ShedLock`/leader election). Worth confirming the scheduler is gated for HA deployments — but this is outside the controller's direct responsibility.

---

## Testing coverage signals
- ✅ Both controllers have dedicated test classes; service has its own test (`ChartServiceImplTest`).
- ✅ Success **and** failure paths exist for at least the monthly endpoint.
- ⚠️ Cannot confirm coverage of: auth/authorization paths, input validation failures (malformed dates, missing premise), and reactive backpressure/cancellation. These are the usual gaps in WebFlux controller suites.
- ⚠️ No visible integration test that exercises the actual HTTP layer (`WebTestClient`). All visible tests call the controller method directly, bypassing routing, filters, content negotiation, and `@Valid`.

---

## Recommended next actions (priority order)
1. **(High)** Read `ChartController.java` and `PrivateChartController.java` to confirm `@SkalboxSecured` is applied on every private endpoint and that user-scoped inputs are authorized against the principal.
2. **(High)** Confirm `ChartApiException` is mapped by a global error handler and that upstream error messages are not echoed to clients.
3. **(Medium)** Add at least one `WebTestClient`-based integration test per controller to exercise the real HTTP path (validation, content type, status codes).
4. **(Medium)** Replace `@SpringBootTest` in controller unit tests with `@ExtendWith(MockitoExtension.class)` or `@WebFluxTest` to reduce CI cost.
5. **(Low)** Fix `tesMonthly_Fail` typo; run formatter on the chart test package.

If you can grant read access to `F:\02_SPG_PROJECTS\skalbox-api\src\main\java\io\spdigital\skalbox\chart\**`, I can re-run the review against the actual controller and service source and either confirm or retire the HIGH-severity items.
