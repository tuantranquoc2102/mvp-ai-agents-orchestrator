# Scope

_Agent: `sa` (Solution Architect)_  
_Status: `success` · attempts: 1_

---

I don't have file-read permission for the project paths, so I can't directly grep for `/monthly` references. Based on the partial `source_scan` (Spring Boot / Java, package `io.spdigital.skalbox`, gradle build, `accounts` module visible) and the intake brief, here is my best-effort architecture map of what the migration will likely touch. Items marked **(verify)** need confirmation by grepping for `monthly`, `Monthly`, `jarvis`, and `JarvisClient`/`JarvisService` once read access is granted.

---

## Likely Impact Map — `/monthly` Migration (skalbox-api ⇐ jarvis-api)

### 1. API layer (controllers / routing) — `skalbox-api`
- `**/controller/**/MonthlyController.java` or `**/web/**/MonthlyController.java` **(verify)** — owns the `/monthly` route; signature and `@RequestMapping`/`@GetMapping` must remain unchanged to preserve the contract.
- OpenAPI / Swagger annotations on that controller (if present).
- `Skalbox-api.postman_collection.json` — the `/monthly` request example should still pass post-migration; useful as a regression artifact.

### 2. Service layer — `skalbox-api`
- `**/service/**/MonthlyService(Impl).java` **(verify)** — currently delegates to a Jarvis client; will absorb the ported logic.
- New service(s) created from `jarvis-api`’s `/monthly` handler chain (calculators, aggregators, formatters). These should land in a clearly named sub-package (e.g. `io.spdigital.skalbox.monthly.service`).
- Any cross-cutting helpers (date/period utilities, unit converters, chart aggregators) referenced by Jarvis’s monthly flow.

### 3. Outbound client layer (to be removed/neutralized) — `skalbox-api`
- `**/client/**/JarvisClient.java`, `**/client/jarvis/**` **(verify)** — the HTTP client used to call jarvis-api’s `/monthly`. Either delete (if Jarvis is only used by `/monthly`) or trim the monthly method.
- Feign/RestTemplate/WebClient bean wiring for Jarvis.
- Retry/circuit-breaker config (Resilience4j / Spring Retry) tied to the Jarvis client.

### 4. DTO / model layer — `skalbox-api`
- Existing request/response DTOs for `/monthly` (must stay wire-compatible).
- New DTOs ported from `jarvis-api` (internal computation models — keep these package-private if they are not part of the public contract).
- Mappers (MapStruct or manual) between Jarvis-side internal models and the existing `skalbox-api` response DTO.

### 5. Repository / data-access layer — `skalbox-api`
- Any repositories Jarvis hit directly (DB, cache, external API). If Jarvis read from its own datastore, `skalbox-api` will need either (a) new repositories pointed at the same datastore, or (b) the upstream data sources Jarvis itself consumed. **This is the biggest unknown — flag below.**
- JPA entities for any tables Jarvis owned that `/monthly` reads.

### 6. Config — `skalbox-api`
- `src/main/resources/application*.yml` / `application*.properties` — remove `jarvis.*` base URL, timeouts, credentials; add any new config keys needed by the ported logic (DB pool sizing, external API creds, feature flags).
- `build.gradle` — drop unused HTTP-client dependencies if no other flow uses Jarvis; add any libraries Jarvis pulled in (e.g. a math/stats lib).
- `deploy/Jenkinsfile.cicd.groovy` — sanity check env-var injection (no stale `JARVIS_*` vars).
- `deploy/resources/cacerts` — only relevant if Jarvis required a custom TLS trust anchor that can now be removed.
- Spring `@Configuration` classes that registered Jarvis beans / `WebClient.Builder` / interceptors.

### 7. UI
- None in scope — `skalbox-api` is a backend service. The downstream UI continues to call `/monthly` unchanged, so contract preservation is the only UI-facing concern.

### 8. Cross-cutting
- Global `@ControllerAdvice` / exception handlers — make sure exception types thrown by the new in-process logic still map to the same HTTP error payloads Jarvis produced.
- Logging/MDC: add trace logs equivalent to those previously emitted by Jarvis so observability isn’t lost.
- Validation annotations on the request DTO (no change expected, but re-verify).

### 9. Tests
- `src/test/java/**/MonthlyControllerTest.java`, `MonthlyServiceTest.java` **(verify)**.
- Existing tests that stub the `JarvisClient` — those stubs become dead code; rewrite to exercise the ported logic directly.
- New unit tests for migrated calculators/aggregators (port from `jarvis-api` tests where they exist).
- Integration test (`@SpringBootTest` + MockMvc) hitting `/monthly` end-to-end with no Jarvis WireMock.
- Postman collection run as a smoke check.

---

## Risk Flags

| # | Risk | Why it matters | Mitigation |
|---|---|---|---|
| R1 | **Data-source ownership of `/monthly` inputs is unknown** | If Jarvis read from a DB/cache/3rd-party that `skalbox-api` does not currently access, the “simple migration” becomes an integration project (new datasource creds, network/firewall, schema duplication, possible read-replica concerns). | Inspect Jarvis’s monthly service for repositories and outbound clients **before** sizing the work. |
| R2 | **Hidden Jarvis dependencies beyond `/monthly`** | The intake says to remove the Jarvis client only if not shared. If other endpoints still use Jarvis, partial cleanup can leave dead config or broken DI. | Grep `JarvisClient`/`jarvis.` across `skalbox-api`; only delete what is exclusively monthly. |
| R3 | **Contract drift** | Even small differences (number rounding, timezone, null vs empty list, ordering) will break the UI/chart. | Capture a recorded `/monthly` response from the current Jarvis-backed flow as a golden fixture; assert byte/JSON equality post-migration. |
| R4 | **Exception/error-payload divergence** | Jarvis errors propagated via the HTTP client are translated by `skalbox-api`’s `ControllerAdvice`. Ported in-process exceptions may follow a different path and produce different status codes/bodies. | Add explicit tests for 4xx/5xx cases (bad input, downstream failure, timeout) and compare payloads. |
| R5 | **Timeouts / SLA characteristics change** | Removing the network hop generally improves latency but also removes the implicit circuit breaker. Long-running monthly aggregations could now block a `skalbox-api` worker thread. | Confirm thread-pool sizing; consider `@Async` or reactive if the computation is heavy. |
| R6 | **Auth/secrets that Jarvis held** | Jarvis may have credentials (DB user, 3rd-party API key) that `skalbox-api` does not currently possess. | Audit Jarvis’s `application.yml` and Vault/secret-manager entries; provision equivalents for `skalbox-api`. |
| R7 | **Shared utility code with subtly different behavior** | Both repos may have a `DateUtils` / `MoneyUtils` / `Period` enum with the same name but different impl. Copy-paste will compile but produce wrong numbers. | Namespace ported utilities (e.g. `monthly.internal.util`) and unit-test parity against Jarvis outputs. |
| R8 | **Caching layer assumptions** | If Jarvis cached monthly aggregates (Caffeine/Redis), the new in-process path will hit cold sources every time, possibly hammering downstream systems. | Decide whether to port the cache; if yes, replicate TTL/keying exactly. |
| R9 | **Truncated source_scan** | The scan was cut off after `accounts/dto`; controllers, services, clients are not visible in the snapshot. | Re-scan with a larger limit or filter to `**/Monthly*`, `**/Jarvis*` before finalizing the file list. |
| R10 | **CI/CD env vars left behind** | Stale `JARVIS_BASE_URL` etc. in Jenkins/Helm/K8s manifests will not fail the build but pollute config and confuse future readers. | Grep the deploy folder and any Helm/K8s chart repo for `JARVIS_`/`jarvis-api`. |

---

## Recommended next step before implementation
Grant read access to both repo roots so the next agent can run:
- `grep -ri "monthly" skalbox-api/src` and `grep -ri "monthly" jarvis-api/src`
- `grep -ri "jarvis" skalbox-api/src`

That will turn every **(verify)** above into a concrete file list and resolve R1, R2, and R9.
