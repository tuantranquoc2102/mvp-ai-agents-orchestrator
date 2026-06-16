# Test Plan

_Agent: `tester` (QA / Tester)_  
_Status: `success` · attempts: 1_

---

# Test Strategy — `/monthly` Migration (jarvis-api → skalbox-api)

## Guiding principle

This is a **logic-relocation migration with a backward-compat contract**. The dominant testing tactic is **golden-output regression**: capture the SOURCE (jarvis-api `/monthly`) response surface *before* any code moves, then assert the TARGET (skalbox-api `/monthly`) matches byte-for-byte (modulo ordering/whitespace). Everything else is a supporting layer.

---

## Layered test plan

### Layer 1 — Golden-output regression (THE critical layer)

**Touches:** end-to-end at the HTTP boundary. Cross-service: SOURCE jarvis-api → captured fixtures → TARGET skalbox-api.

**Sequence (must happen in this order):**

1. **Before any code is moved**, stand up jarvis-api locally against a frozen DB snapshot (see "Data fixture freeze" below).
2. Drive `/monthly` through Postman/`curl` with the matrix below, save each response to `skalbox-api/src/test/resources/monthly/baseline/<case>.json`.
3. Commit these fixtures in the **first** migration PR — they become the immovable oracle.
4. Post-migration, a parametrized test (`MonthlyGoldenOutputTest`) replays each request against skalbox-api and asserts `JSONAssert.assertEquals(expected, actual, LENIENT)` for field-set equality, then `STRICT` for ordering-sensitive fields (lists, time series).

**Request matrix (minimum):**
| Case | Why |
|---|---|
| Current month, single tenant, full data | Happy path |
| Year boundary (Dec→Jan request) | Off-by-one risk |
| Leap-year February | Date math |
| Month with zero activity | Empty-collection serialization (`[]` vs `null` — common silent break) |
| Month with one partial-day record | Aggregation edge |
| Invalid month param (`13`, `0`, `"abc"`) | Validation + error payload |
| Missing required param | `@ControllerAdvice` mapping |
| Auth missing / wrong tenant | Security path (unchanged but must be re-verified) |
| Locale/timezone variant if endpoint accepts it | TZ math is a top-3 silent-break risk |
| Large month (high-volume tenant) | Pagination / streaming / numeric precision |

**Tolerance rules — decide explicitly, don't drift:**
- Field ordering in JSON objects: ignored (Jackson default differs across versions).
- Array ordering: **strict** unless source explicitly documents unordered — array reordering is the #1 source of "looks fine, breaks the client".
- Floating-point: strict equality first; if SOURCE uses `BigDecimal`, lock scale/rounding mode in the port and assert string-equal serialized form.
- Trailing nulls: strict — `{"x": null}` vs `{}` breaks deserializers in some clients.

### Layer 2 — Unit tests on ported logic

**Touches:** the ported `MonthlyComputationService` and any helpers/mappers/aggregators copied verbatim from jarvis-api.

- Port jarvis-api's existing unit tests **verbatim** in the same commit as the production code. Same assertions, same fixtures, only package-rename diffs. If a jarvis test fails on port, that's a porting bug — fix the port, not the test.
- Add unit tests **only** where jarvis-api had gaps that the regression matrix above already revealed risk in (e.g., leap-year date math) — don't speculatively expand.
- Mock all repositories. These tests must not touch a DB.

### Layer 3 — Repository / data-access integration tests

**Touches:** any `*Repository` newly ported from jarvis-api, or any existing skalbox repo whose query is now exercised by `/monthly` for the first time.

- Use Testcontainers (Postgres/MySQL — match prod) with a Flyway/Liquibase migration replay. **Do not** use H2 even if jarvis-api did — H2 SQL dialect drift is a classic source of "passed locally, failed in prod."
- Seed each test with the smallest representative dataset.
- Assert raw repository output, not the HTTP response — keeps failure localization clean.
- Critical: if jarvis-api and skalbox-api pointed at the **same** physical DB but used **different schema names / search_path / connection pool sizing**, add a test that pins the resolved table identifier. Cross-schema mistakes are silent.

### Layer 4 — Web slice / controller integration

**Touches:** `MonthlyController` + DTO mapping + `@ControllerAdvice` + security filter chain.

- `@WebMvcTest(MonthlyController.class)` with the computation service mocked.
- Assert: HTTP status codes, response Content-Type, validation error payload shape, auth challenges.
- This is the layer that catches "contract is the same but someone swapped `@RequestParam` for `@PathVariable`" — a small but real risk in a copy-port.

### Layer 5 — Full SpringBootTest end-to-end

**Touches:** skalbox-api in-process, real DB (Testcontainers), real bean wiring, real serialization, **no** jarvis-api running.

- This is where the Layer-1 golden-output fixtures get replayed in CI on every PR.
- Also where you assert `JarvisClient` and its Feign config are **gone** — a `@Test` that `applicationContext.getBeansOfType(JarvisClient.class)` is empty prevents accidental resurrection during a future merge.

### Layer 6 — Live cross-service diff (manual, pre-merge gate)

**Touches:** both services deployed to a shared staging env, same DB.

- Run a small shell script that hits both `/monthly` endpoints with the request matrix and `diff`s the JSON. Any non-whitespace diff blocks merge.
- This is the only test that catches "the fixtures captured in Layer 1 don't actually reflect prod jarvis-api because someone snapshotted wrong" — a known own-goal in this kind of migration.

---

## Regression risks — ranked, with mitigations

| # | Risk | Likelihood | Mitigation |
|---|---|---|---|
| 1 | **Array ordering drift** when porting Stream pipelines / `Collectors.toMap` (HashMap → unordered) | High | Strict-order JSON assertions in Layer 1; add explicit `.sorted(...)` in ported code where SOURCE relied on insertion-ordered LinkedHashMap |
| 2 | **Timezone / clock source** difference between services (`ZoneId.systemDefault()` vs explicit `UTC`) | High | Pin `Clock` bean in tests; include a TZ-sensitive case in the golden matrix; grep ported code for `LocalDate.now()` / `new Date()` and replace with injected `Clock` |
| 3 | **BigDecimal scale/rounding** changes when re-serialized via skalbox-api's Jackson config | Medium-High | Layer 1 strict equality on serialized form; if mismatch, lock `JsonSerializer<BigDecimal>` to jarvis-api's config |
| 4 | **Null vs empty collection** in response (Jackson `@JsonInclude` default differs across modules) | Medium-High | Include "month with zero activity" in matrix; pin `spring.jackson.default-property-inclusion` to whatever jarvis-api emits |
| 5 | **Schema/datasource divergence** — ported repo queries a table that doesn't exist or has different columns in skalbox's datasource | Medium | Hard gate in Step 0 of architect plan; Layer 3 Testcontainers with prod-equivalent migrations catches this in CI |
| 6 | **Cache behavior change** — jarvis-api's `@Cacheable` not ported, so first-request latency / load profile changes silently | Medium | Add a load-shape smoke test in staging; document cache config in the port or explicitly decide to drop it |
| 7 | **Transaction boundaries** — jarvis service had `@Transactional(readOnly=true)`, port forgets it → connection-pool pressure change | Medium | Grep `@Transactional` on every ported class and preserve attributes verbatim |
| 8 | **Lazy-loading / N+1** — port copies entity graph traversal that worked under jarvis's session config but blows up under skalbox's | Medium | Layer 3 test asserts query count via `datasource-proxy` or Hibernate statistics for the high-volume month case |
| 9 | **Validation message wording** in error payload — jarvis used a custom `MessageSource`, skalbox uses default | Low-Medium | Layer 1 strict equality on error payloads (matrix cases 6 & 7) |
| 10 | **Bean name collisions** — ported `MonthlyComputationService` shadows an existing bean or vice versa | Low | Context-loads test in Layer 5 catches at startup |
| 11 | **Logging / MDC contract** — downstream log-scraping pipelines depend on jarvis-api's log lines | Low | If known, port log statements verbatim including levels and key names; otherwise document the change |
| 12 | **JarvisClient resurrection** in a parallel feature branch merged after the migration | Low | Explicit "no JarvisClient bean" assertion test (Layer 5) |

---

## Data fixture freeze

The golden-output approach is only as good as the data it's captured against. Concretely:

- Take a **point-in-time dump** of the production-equivalent dataset used to generate Layer 1 fixtures. Store it as a Testcontainers init script (`monthly-baseline.sql`) checked into the repo.
- Layer 3 and Layer 5 tests load **this exact dump**. Layer 1 fixtures and Layer 3/5 results are therefore comparable.
- If the dump is too large or contains PII, generate a synthetic one that reproduces every matrix case and use *that* as the canonical baseline — but then capture Layer 1 fixtures from jarvis-api running against the synthetic dump, **not** from prod. Don't mix sources.

---

## CI gating

- Layers 2–5 run on every PR; failure blocks merge.
- Layer 1 golden-output test is the headline check — name it so it's obvious in PR reviews (`MonthlyGoldenOutputTest`).
- Layer 6 (live diff) runs nightly in staging plus as a manual pre-merge action on the migration PR itself.

---

## What I'd cut if time is short

If forced to ship with less: keep Layers 1, 3, and 5. Skip Layer 4 (controller slice) — Layer 5 covers it end-to-end, just with worse failure localization. Do **not** skip Layer 1 — without the golden fixtures, this migration has no oracle and "backward compatible" becomes vibes.
