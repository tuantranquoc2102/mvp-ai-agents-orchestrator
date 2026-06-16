# Architecture

_Agent: `architect` (Software Architect)_  
_Status: `success` · attempts: 1_

---

# Architect Plan — `/monthly` Logic Migration (jarvis-api → skalbox-api)

> **Note on file paths:** Both the SA and I lack read access to `F:\02_SPG_PROJECTS\skalbox-api-jarvis-api-month-chart\*`. Paths in this plan use the SA's discovery pattern (Spring Boot, `io.spdigital.skalbox`) and are marked **(verify)** where they must be confirmed by grep on first read. The shape of the plan and the sequencing are independent of those verifications.

---

## 1. Data Model Touches

**Expected impact: zero schema changes.** The endpoint is a chart/aggregation read, and the intake explicitly puts DB schema changes out of scope.

What *does* change on the data side:

| Concern | Action |
|---|---|
| Read sources used by Jarvis (`/monthly` upstream) | Inventory in `jarvis-api` — list every JPA repo, JDBC template, or external read the Jarvis handler hits. **(verify)** |
| Repository availability in skalbox-api | For each read source above, check if an equivalent `*Repository` already exists in `skalbox-api`. If yes → reuse. If no → port the repo interface + any custom queries verbatim. |
| Entities / JPA mappings | If Jarvis owns entities not present in skalbox-api, copy them under `io.spdigital.skalbox.monthly.domain.entity` and confirm the `@Table`/`@Column` mappings match the same DB. **(verify same datasource)** |
| Connection / datasource config | If Jarvis pointed at a different schema/DB, confirm skalbox-api's `application.yml` datasource can reach the same tables; otherwise add the datasource. **Hard gate — do not proceed if datasources diverge without sign-off.** |
| Caches | If Jarvis uses `@Cacheable` on monthly queries, port the cache region + config to skalbox-api so warm/cold behavior is preserved. |

---

## 2. API Contracts

**Public contract: unchanged.** The acceptance criteria mandate backward compatibility.

- `MonthlyController` in skalbox-api **(verify path: `**/controller/MonthlyController.java`)** keeps the same:
  - HTTP method, path (`/monthly`), and any path/query/header params
  - Request DTO field names, types, validation annotations
  - Response DTO field names, types, ordering, null handling
  - HTTP status codes for success and each error case
  - Exception → error-payload mapping (preserve current `@ControllerAdvice` behavior)

- **Internal contract changes (acceptable):**
  - `MonthlyService` signature may stay the same; its body changes from "call JarvisClient → map" to "call internal computation".
  - New internal service interfaces created from Jarvis logic are free to use idiomatic skalbox-api package names. Put them in `io.spdigital.skalbox.monthly.service` to keep blast radius small.

- **Postman regression artifact:** `Skalbox-api.postman_collection.json` — the `/monthly` request must produce byte-identical (modulo whitespace/ordering) response before and after. Snapshot the current response in a test fixture *before* deleting JarvisClient.

---

## 3. Sequence of Operations (Migration Steps, in order)

Do these in order. Each step is independently buildable so the branch stays green.

### Step 0 — Establish a regression baseline (before touching code)
1. Start both services locally.
2. Hit `/monthly` with representative inputs (happy path + at least one validation error + one downstream-failure case).
3. Save responses as JSON fixtures under `skalbox-api/src/test/resources/monthly/baseline/`. These become the contract assertion in Step 6.

### Step 1 — Inventory in jarvis-api **(verify all paths)**
Grep targets to run *first*:
- `grep -rE "@(Get|Post|Request)Mapping.*monthly" jarvis-api/src`
- `grep -r "class .*Monthly" jarvis-api/src`
- From the controller, follow the call graph: controller → service → (mapper | repo | helper | constants).
Produce a flat list of files to port. The SA's "Likely Impact Map" §2 is the template.

### Step 2 — Inventory in skalbox-api **(verify all paths)**
- `grep -rE "@(Get|Post|Request)Mapping.*monthly" skalbox-api/src` → confirms `MonthlyController` location.
- `grep -r "Jarvis" skalbox-api/src` → finds `JarvisClient`, Feign interfaces, config, properties. Tag each result: *(used only by `/monthly`)* vs *(shared)*.

### Step 3 — Port code into skalbox-api under a new package
Land everything under a single new package so it's easy to review and to revert:

```
io.spdigital.skalbox.monthly
├── service
│   ├── MonthlyComputationService.java        // ported from jarvis-api service
│   └── (helpers, aggregators)
├── domain
│   ├── model   // internal value objects ported from jarvis
│   └── entity  // only if jarvis owned entities not in skalbox
├── repository  // only if jarvis owned repos not in skalbox
└── mapper      // jarvis-internal mappers (NOT the controller-facing DTO mapper)
```

- Copy classes **verbatim first** (preserve method bodies, log messages, exception types). Rename package only.
- Resolve compile errors by adding missing imports / dependencies. Do not "improve" logic in this pass — that's a separate cleanup commit later.
- If jarvis-api used libs that skalbox-api lacks, add them to `skalbox-api/build.gradle` **(verify gradle vs pom)**. Pin to the same version jarvis-api used.

### Step 4 — Swap the call site
In `MonthlyService` (skalbox-api) **(verify)**:
- Replace the `jarvisClient.getMonthly(...)` call with `monthlyComputationService.compute(...)`.
- Keep the outer service's input mapping and the outbound response mapping intact — only the middle changes.
- One commit, one diff. This is the smallest reviewable unit.

### Step 5 — Remove the Jarvis client surface
Only after Step 6 (tests) passes locally:
- Delete `JarvisClient` / Feign interface / `@FeignClient` config **(verify)**.
- Delete `jarvis-api` properties from `application.yml` / `application-*.yml` (base-url, timeouts, retry).
- Remove Resilience4j / Spring Retry config keys tied to Jarvis.
- Remove Jarvis-related beans / `@Configuration` classes.
- Drop the Feign / WebClient dependency from `build.gradle` only if no other code uses it.

If `grep -r "Jarvis" skalbox-api/src` returns anything afterward → it's stale; remove.

### Step 6 — Tests
- **Unit tests:** port the existing jarvis-api unit tests for the migrated services into `skalbox-api/src/test/java/io/spdigital/skalbox/monthly/service/`. Same assertions, new package.
- **Integration test:** one Spring Boot test that hits `/monthly` via `MockMvc` / `TestRestTemplate` and asserts the response equals the Step 0 baseline fixture. This is the contract gate.
- **Negative tests:** at minimum one validation error and one downstream-data-missing case, asserting the same HTTP status + error payload as before.
- Delete any existing test that mocked `JarvisClient` for `/monthly` — they're now meaningless.

### Step 7 — Logging
- Add `DEBUG` traces at entry/exit of `MonthlyComputationService` and at each aggregation boundary. Use the same MDC keys (`requestId`, `userId`, etc.) the rest of skalbox-api uses — **(verify the MDC convention by grepping an existing controller)**.
- Do *not* add `INFO`-level chatter for per-request flow; that produces log spam in prod.

### Step 8 — Build + verify
- `./gradlew clean build` (or `mvn` **(verify)**) green.
- Manual smoke against the Postman collection.
- Confirm `grep -r "jarvis" skalbox-api/src` returns nothing case-insensitive.

---

## 4. Error Handling

The migration must **preserve observable error behavior**, not necessarily preserve exception *class names*. Concretely:

| Original (Jarvis-mediated) | After migration | Notes |
|---|---|---|
| HTTP 4xx from Jarvis client mapped to a skalbox exception | Internal `IllegalArgumentException` / domain exception of the same semantic class | Map via existing `@ControllerAdvice` so the response payload is identical |
| HTTP 5xx / timeout from Jarvis | Domain `MonthlyComputationException` (new, in `monthly.service`) | Map to the same HTTP status (likely 500/502) the client previously returned |
| Jarvis returns empty / "not found" | Same empty/404 response from skalbox-api | Don't silently switch from 404 → 200-empty-list |
| Validation failures on `/monthly` request | Unchanged — `@Valid` + `MethodArgumentNotValidException` handler already in skalbox-api | No work, just verify with a negative test |

**Two error-handling traps to watch for:**

1. **Wrapped exceptions disappear.** If skalbox-api's `@ControllerAdvice` catches `FeignException` specifically to translate Jarvis errors, that branch becomes dead code after Step 5. Delete it, but first confirm no internal `IOException` paths now leak through to the default handler (which usually returns generic 500). Add an explicit `@ExceptionHandler(MonthlyComputationException.class)` if needed.

2. **Transactional boundaries.** Jarvis ran its DB reads in its own transaction. After migration, those reads run inside the skalbox-api request thread. If the migrated repo uses `@Transactional`, confirm propagation behavior — particularly if the caller in skalbox-api is already inside a transaction (`REQUIRED` is usually safe; `REQUIRES_NEW` may not be).

**Logging on errors:** every caught exception in `MonthlyComputationService` must log at `WARN` (expected/validation) or `ERROR` (unexpected) with the MDC `requestId`. Match the existing skalbox-api convention.

---

## 5. Risk + Rollback

- **Rollback strategy:** Steps 3–7 are additive until Step 5. Until Step 5 is merged, `JarvisClient` still exists; flipping `MonthlyService` back to call it is a one-line change. Stage the work so Step 5 is the last commit before the PR is merged — keep the deletion separable from the swap.
- **Feature-flag option (if the team uses one):** wrap the Step 4 swap in a config flag (`skalbox.monthly.use-internal=true`) and default it off in non-prod. Useful only if Jarvis is still running and there's appetite for a canary; otherwise it's overhead.
- **Highest-risk item:** datasource parity (§1). If jarvis-api and skalbox-api point at different DBs/schemas, the whole migration shape changes — this needs to be confirmed in Step 1.

---

## 6. Open Items Requiring Verification on First Read

These must be resolved before code changes start:

1. Exact path of `MonthlyController` and `MonthlyService` in skalbox-api.
2. List of all classes referenced from jarvis-api's `/monthly` handler.
3. Whether jarvis-api and skalbox-api share the same datasource(s).
4. Build tool: Gradle vs Maven (SA noted Gradle — confirm).
5. HTTP client in use for `JarvisClient`: Feign / WebClient / RestTemplate (affects what to remove in Step 5).
6. Whether `/monthly` is the *only* Jarvis caller (decides full vs partial Jarvis cleanup).
7. MDC / logging convention used elsewhere in skalbox-api (so Step 7 matches).

Hand this list to the implementer as the first grep batch; everything downstream is contingent on its answers.
