# Backend Plan

_Agent: `be_dev` (Backend Developer)_  
_Status: `success` · attempts: 1_

---

# Backend Implementation Plan — `/monthly` Logic Migration (jarvis-api → skalbox-api)

**Role:** Backend Developer
**Branch:** `skalbox-api-jarvis-api-month-chart` (existing feature branch)
**Scope:** Inline jarvis-api `/monthly` computation into skalbox-api; remove JarvisClient dependency. No DB schema changes. Public contract unchanged.

> Paths marked **(verify)** must be confirmed via grep on first read before edits. Verification commands listed in §6.

---

## 1. Database Migrations

**None.** Zero schema changes per architect contract. Verification gates:

- Confirm both services point to the **same datasource** (`spring.datasource.url` in `skalbox-api/src/main/resources/application*.yml` matches jarvis-api's). **Hard gate — stop if diverged.**
- If jarvis-api uses a dedicated cache region (e.g. `@Cacheable("monthly")`), port the cache config block into skalbox-api's existing cache configuration (likely `CacheConfig.java` — **verify**). No new infra, just register the region name.

---

## 2. Files to CREATE (new package: `io.spdigital.skalbox.monthly`)

All new files land under `skalbox-api/src/main/java/io/spdigital/skalbox/monthly/` to keep blast radius small and revert trivial.

### 2.1 `service/MonthlyComputationService.java`
Ported verbatim (body) from jarvis-api's monthly service. Renamed package only.

```java
public interface MonthlyComputationService {
    MonthlyComputationResult compute(MonthlyComputationRequest request);
}
```

### 2.2 `service/impl/MonthlyComputationServiceImpl.java`
Concrete implementation. Same fields and dependencies as jarvis-api's original.

```java
@Service
@RequiredArgsConstructor
public class MonthlyComputationServiceImpl implements MonthlyComputationService {
    private final <PortedRepository1> repo1;
    private final <PortedRepository2> repo2;
    private final MonthlyAggregator aggregator;

    @Override
    public MonthlyComputationResult compute(MonthlyComputationRequest request) { /* ported body */ }
}
```

### 2.3 `service/MonthlyAggregator.java` (only if jarvis-api had one — verify)
Helper(s) for grouping / summing rows.

```java
public class MonthlyAggregator {
    public List<MonthlyBucket> aggregate(List<RawMonthlyRow> rows, ZoneId zone);
}
```

### 2.4 `domain/model/MonthlyComputationRequest.java`
Internal value object — **NOT** the public DTO. Built from the existing public request inside `MonthlyService`.

```java
public record MonthlyComputationRequest(
    LocalDate from,
    LocalDate to,
    String tenantId,
    /* any other fields jarvis service required */
) {}
```

### 2.5 `domain/model/MonthlyComputationResult.java`
Internal value object returned by the computation service. Mapped to the public response DTO by the existing outer service.

```java
public record MonthlyComputationResult(
    List<MonthlyBucket> buckets,
    BigDecimal total,
    /* other internal fields */
) {}
```

### 2.6 `domain/model/MonthlyBucket.java` (and any other inner VOs ported)
```java
public record MonthlyBucket(YearMonth month, BigDecimal value, long count) {}
```

### 2.7 `domain/entity/*.java` — **CREATE ONLY IF** jarvis-api owns JPA entities absent in skalbox-api
For each missing entity, copy the `@Entity`, `@Table`, `@Column`, `@Id` mappings verbatim. Verify same physical table.

### 2.8 `repository/*.java` — **CREATE ONLY IF** jarvis-api owns repositories absent in skalbox-api
For each:
```java
public interface PortedMonthlyRepository extends JpaRepository<Entity, Long> {
    @Query(/* exact JPQL/SQL from jarvis-api */)
    List<Row> findForMonthlyBetween(@Param("from") LocalDate from, @Param("to") LocalDate to);
}
```

### 2.9 `mapper/*Mapper.java` — internal mappers (NOT controller-facing)
Port any MapStruct or hand-written mapper used between jarvis's internal models. Public-facing `MonthlyResponseMapper` already exists in skalbox-api and is untouched.

### 2.10 Test fixtures (created in **Step 0** before code work)
- `src/test/resources/monthly/baseline/happy-path-request.json`
- `src/test/resources/monthly/baseline/happy-path-response.json`
- `src/test/resources/monthly/baseline/validation-error-request.json`
- `src/test/resources/monthly/baseline/validation-error-response.json`
- `src/test/resources/monthly/baseline/downstream-failure-request.json`
- `src/test/resources/monthly/baseline/downstream-failure-response.json`

### 2.11 New tests
- `src/test/java/io/spdigital/skalbox/monthly/service/MonthlyComputationServiceImplTest.java` — unit test on the ported service with mocked repos. Cover happy path, empty result, edge dates (month boundary, leap year), and exception propagation.
- `src/test/java/io/spdigital/skalbox/monthly/MonthlyContractRegressionTest.java` — `@SpringBootTest` + `MockMvc` test that loads each baseline fixture, hits `/monthly`, and asserts the response matches the saved baseline JSON (using JSONassert with `LENIENT` ordering, `STRICT` on values).

---

## 3. Files to MODIFY

### 3.1 `controller/MonthlyController.java` **(verify path)**
**No changes.** Public contract frozen. If a method-level `@Tag`/OpenAPI annotation references jarvis, that may be cleaned up but is non-functional.

### 3.2 `service/MonthlyService.java` **(verify path)** — the existing outer service
**One-line behavioral swap.** Keep input/output mapping; replace the Jarvis call.

Before:
```java
private final JarvisClient jarvisClient;
...
JarvisMonthlyResponse upstream = jarvisClient.getMonthly(jarvisRequest);
```

After:
```java
private final MonthlyComputationService monthlyComputationService;
...
MonthlyComputationResult result = monthlyComputationService.compute(toComputationRequest(publicRequest));
```

Function signature unchanged:
```java
public MonthlyResponse getMonthly(MonthlyRequest request);
```

Add a small private mapper:
```java
private MonthlyComputationRequest toComputationRequest(MonthlyRequest req);
private MonthlyResponse toPublicResponse(MonthlyComputationResult result);
```
Keep the public-response mapping identical to today so the contract test passes byte-for-byte.

### 3.3 `application.yml` and `application-*.yml` (all profiles) **(verify)**
**Remove only after Step 6 passes.**
- Remove `jarvis.api.base-url`, `jarvis.api.timeout`, `jarvis.api.auth.*`, any Feign-specific config keys.
- Leave any property that is still referenced by other code (grep first — see §6).

### 3.4 `build.gradle` (or `pom.xml`) **(verify build tool)**
- Add any library jarvis-api used that skalbox-api lacks (pin to jarvis-api's version exactly).
- **Defer** removing `spring-cloud-starter-openfeign` until §4.4 confirms no other Feign client uses it.

### 3.5 Cache config (e.g. `config/CacheConfig.java`) **(verify exists)**
- Register the monthly cache region if jarvis-api used `@Cacheable` on monthly results.

---

## 4. Files to DELETE (only after Step 6 green)

### 4.1 `client/JarvisClient.java` (Feign interface) **(verify)**
### 4.2 `config/JarvisFeignConfig.java` **(verify)**
### 4.3 `dto/jarvis/*.java` — jarvis-specific request/response DTOs used only by `JarvisClient`
### 4.4 `@EnableFeignClients` annotation
- If it appears on the main `@SpringBootApplication` class and **no other Feign client exists** (verify with grep `@FeignClient`), remove it and drop the openfeign starter from the build file.
- If other Feign clients exist, leave it.

### 4.5 Any `JarvisClientProperties.java` / `@ConfigurationProperties` for jarvis

---

## 5. External Calls

### 5.1 Removed
- **HTTP call to jarvis-api `/monthly`** — eliminated. No more outbound Feign request from skalbox-api to jarvis-api for this path.

### 5.2 Added
- **None.** The ported logic uses repositories already inside skalbox-api (or newly ported ones hitting the same shared DB).

### 5.3 Unchanged
- Any DB reads via JPA repositories. Same datasource. Same SQL (verbatim port).

### 5.4 Observability deltas to expect
- Outbound HTTP metrics for jarvis-api drop to zero — coordinate with ops to update any dashboards/alerts that reference the jarvis call.
- DB query volume on skalbox-api's datasource will increase by exactly the jarvis call volume on the same tables. Net cluster load is unchanged (jarvis-api previously did the same reads).

---

## 6. Pre-Work Verification Commands

Run these **before** opening any file. Resolve every **(verify)** marker above using the results.

```bash
# skalbox-api side
grep -rnE "@(Get|Post|Request)Mapping.*monthly" skalbox-api/src/main/java
grep -rn  "class .*Monthly"                       skalbox-api/src/main/java
grep -rn  "Jarvis"                                skalbox-api/src
grep -rn  "@FeignClient"                          skalbox-api/src/main/java
grep -rn  "@EnableFeignClients"                   skalbox-api/src/main/java
grep -rn  "jarvis"                                skalbox-api/src/main/resources
ls skalbox-api/ | grep -E "build.gradle|pom.xml"

# jarvis-api side (source of truth for ported logic)
grep -rnE "@(Get|Post|Request)Mapping.*monthly" jarvis-api/src/main/java
grep -rn  "class .*Monthly"                      jarvis-api/src/main/java
# From the controller, walk the call graph manually: controller → service → repo/helper/mapper.
```

Output of these commands becomes the file-by-file port checklist that drives §2 and §3.

---

## 7. Execution Order (commits on the feature branch)

Each commit must leave the branch green (compiles + tests pass).

| # | Commit | Files |
|---|---|---|
| 0 | `test: capture /monthly baseline fixtures` | §2.10 fixtures + `MonthlyContractRegressionTest` skeleton that loads fixtures and is `@Disabled` |
| 1 | `feat(monthly): port jarvis monthly entities & repositories` | §2.7, §2.8 only — compiles, no behavior change yet |
| 2 | `feat(monthly): port jarvis monthly computation service` | §2.1–§2.6, §2.9 + unit test §2.11 (MonthlyComputationServiceImplTest) |
| 3 | `feat(monthly): switch MonthlyService to internal computation` | §3.2 swap + enable `MonthlyContractRegressionTest` |
| 4 | `chore(monthly): remove JarvisClient and jarvis config` | §4.1–§4.5, §3.3, §3.4 cleanup |
| 5 | `chore: drop openfeign starter` *(only if §4.4 confirms safe)* | `build.gradle` / `pom.xml` |

After commit 3, `/monthly` is fully self-contained. Commits 4–5 are reversible cleanup.

---

## 8. Risks & Gates for the Developer

1. **Datasource drift** — if jarvis-api reads a DB skalbox-api can't reach, STOP and escalate. Do not add a second datasource without sign-off.
2. **Hidden shared state** — if `grep "Jarvis" skalbox-api/src` returns hits outside `/monthly`'s call graph, those are out of scope. Tag and leave; do not delete.
3. **Contract drift** — `MonthlyContractRegressionTest` is the gate. If a baseline diverges by even a field name, fix the internal mapping, do not change the baseline.
4. **Cache semantics** — if jarvis-api results were cached and skalbox-api doesn't port the cache, the first user after deploy will see a latency spike. Port the cache or document the deferral.
5. **Feign removal** — only drop the starter after confirming no other `@FeignClient` exists. Run the grep in §6.

---

## 9. Out of Scope (do NOT touch in this branch)

- Public DTO field names, types, ordering, validation
- HTTP status codes and error envelope shape
- Any other endpoint
- DB schema
- Logic "improvements" inside the ported service (separate refactor commit later)
- Logging format changes
- Deployment scripts / CI config (handled by deployment engineer)
