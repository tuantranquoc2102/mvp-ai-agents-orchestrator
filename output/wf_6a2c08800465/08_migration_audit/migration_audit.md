# Migration Audit

_Agent: `architect` (Software Architect)_  
_Status: `success` · attempts: 1_

---

# Migration Logic-Parity Audit: `/monthly` Endpoint (jarvis-api → skalbox-api)

## Evidence-Access Caveat

The full `migrate_from_scan` / `source_scan` payloads from prior workflow steps were truncated in the inputs I received, and direct read access to the repo paths (`F:\02_SPG_PROJECTS\skalbox-api-jarvis-api-month-chart\jarvis-api` and `\skalbox-api`) is currently **denied** by the sandbox (`Grep` and `Read` both returned permission errors). The partial directory listing I was able to glob shows that **jarvis-api is a Go service** (`cmd/serverd/main.go`, `cmd/serverd/router/handler.go`, `cmd/serverd/router/gateway.go`, `data/migrations/*.sql`, `codegen.go`), while the SA scope brief indicates **skalbox-api is a Spring Boot / Java service** (package `io.spdigital.skalbox`, gradle build). This is a **cross-stack port (Go → Java)**, not a same-language move — every row below is therefore at minimum a *re-implementation* and should be treated with elevated scrutiny.

Rows marked **(unverified — file content unread)** are inferred from the file-name conventions visible in the partial scan and the SA's architecture map; they MUST be re-checked once `Grep`/`Read` permission is granted on both repo roots.

---

## Parity Table

| # | Behavior (SOURCE side: jarvis-api) | Source files (jarvis-api) | Target files (skalbox-api) | Status | Risk |
|---|---|---|---|---|---|
| 1 | HTTP route registration for `/monthly` (and any sub-paths) | `jarvis-api/cmd/serverd/router/gateway.go`, `jarvis-api/cmd/serverd/router/handler.go` (unverified — file content unread) | `skalbox-api/**/controller/**/MonthlyController.java` (unverified — name inferred from SA map) | preserved (contract must remain identical per AC #3) | MEDIUM — Go router pattern (likely chi/gin) vs. Spring `@GetMapping` differ in path-param coercion, trailing-slash, and content-negotiation defaults; silent 404↔405 differences possible |
| 2 | Request validation (query/path params, date/period bounds for "monthly") | `jarvis-api/cmd/serverd/router/handler.go` + any `internal/.../validate*.go` (unverified) | Spring `@Valid` + bean-validation annotations on request DTO; `@ControllerAdvice` (unverified) | changed (Go manual validation → Java bean-validation) | **HIGH** — Go hand-rolled validators frequently differ from JSR-380 in null/empty/zero-value semantics. Silent behavior change candidate. |
| 3 | Core `/monthly` business logic (aggregation / chart shaping) | jarvis-api `internal/**` services invoked by `cmd/serverd/router/handler.go` (specific files unverified — scan truncated) | `skalbox-api/**/service/**/MonthlyService(Impl).java` (new code per migration plan) | changed (Go → Java port) | **HIGH** — language port of business logic is the single largest silent-behavior-change surface. Numeric precision (Go `float64` vs Java `BigDecimal`/`double`), nil-vs-null map handling, slice-order stability all diverge by default. |
| 4 | Date / period / timezone handling for "monthly" buckets | jarvis-api uses Go `time.Time` (files unverified) | skalbox-api will use `java.time.*` (`YearMonth`, `ZonedDateTime`) | changed | **HIGH** — Default zone differs (Go uses `time.Local` of pod; Java uses `TimeZone.getDefault()` / `ZoneId.systemDefault()`). Month boundaries can shift by ±1 day across DST. Silent. |
| 5 | DB access for monthly data (SQL queries, migrations) | `jarvis-api/data/migrations/0001_…0013_*.sql` (visible in scan); query code in `internal/**` (unverified) | skalbox-api JPA/JOOQ/JDBC layer (file names unverified) | preserved if same DB / changed if new repo | **HIGH** if the DB is being shared but skalbox-api uses different ORM dialect (case-folding of identifiers, JSONB casting, `now()` vs `CURRENT_TIMESTAMP`). Schema migrations (`data/migrations/*.sql`) should NOT be re-run from skalbox-api — confirm ownership. |
| 6 | Response payload shape (JSON field names, casing, null vs omitted, number formatting) | jarvis-api response structs serialized via `encoding/json` (files unverified) | skalbox-api response DTO via Jackson (file unverified) | preserved (contract per AC #3) but mechanically changed | **HIGH** — Default behaviors diverge: Go emits `0`/`""`/`false` unless `omitempty`; Jackson by default emits `null`. Field casing: Go uses struct-tag JSON names, Jackson uses property names + `@JsonProperty`. Postman collection (`Skalbox-api.postman_collection.json`) referenced by SA should be diffed byte-for-byte. |
| 7 | Error response format (status code, error code string, message envelope) | jarvis-api error helpers in `cmd/serverd/router/handler.go` and any `internal/errors` package (unverified) | skalbox-api `@ControllerAdvice` / `ResponseStatusException` (unverified) | changed | **HIGH** — Error envelopes almost never round-trip identically across stacks. Silent change to clients that parse `error.code`. |
| 8 | Outbound HTTP call skalbox-api → jarvis-api `/monthly` | n/a (this is the inbound side on jarvis-api) | `skalbox-api/**/client/**/JarvisClient.java` (and Feign/RestTemplate/WebClient wiring) | dropped (per AC #1 — no runtime call to jarvis-api) | LOW if usage is exclusive to `/monthly`; MEDIUM if `JarvisClient` is shared and only the monthly method should be removed |
| 9 | Resilience config (retry, timeout, circuit-breaker) on the Jarvis call path | n/a on source | Resilience4j / Spring Retry annotations on `JarvisClient` (unverified) | dropped | MEDIUM — Removing the client also removes its retry/timeout safety net. The new in-process logic inherits NO retry. If the original Jarvis logic did any internal retry (e.g., DB retry inside jarvis-api), it must be re-implemented in skalbox-api. **HIGH** if not audited. |
| 10 | Authentication / authorization on `/monthly` (token validation, scopes) | jarvis-api middleware in `cmd/serverd/router/gateway.go` (unverified — file content unread) | skalbox-api Spring Security filter chain | changed (jarvis-side auth is dropped; skalbox-side auth must cover the union) | **HIGH** — If jarvis-api previously enforced an extra scope/role check that skalbox-api does not, the migration silently lowers the auth bar. Must diff filter chains. |
| 11 | Logging / tracing of the `/monthly` flow | jarvis-api logger in `cmd/serverd/router/handler.go` (unverified) | skalbox-api SLF4J + Sleuth/Micrometer (unverified) | changed (per AC #9 — new trace logs required) | LOW (intentional change) — but verify log levels/field names match ops dashboards |
| 12 | Configuration / env vars consumed by `/monthly` (DB DSN, feature flags, limits) | `jarvis-api/cmd/appconfig/default_app_cfg.go`, `jarvis-api/cmd/serverd/envvar/validate.go`, `jarvis-api/.env.dev` | skalbox-api `application.yml` / `@ConfigurationProperties` (unverified) | changed (renamed / re-keyed) | **HIGH** — Silent default-value drift: e.g., a Go `int` config default of `0` may become Spring's `null` Integer. Re-validate every monthly-related config key. K8s configmaps (`build/cd/k8s/{dev,qa,prod}/configmap.yaml`) must also be ported. |
| 13 | DB schema migrations associated with monthly tables | `jarvis-api/data/migrations/0001_…0013_*.up.sql` / `*.down.sql` | skalbox-api migration tooling (Flyway/Liquibase, unverified) | preserved if DB shared / migrated if not | **HIGH** — If skalbox-api owns the DB now, the `0001…0013` history must be reconciled. Re-applying migrations against an existing schema will fail; skipping them loses provenance. Confirm baseline strategy. |
| 14 | Code generation (`codegen.go`) outputs consumed by monthly path (OpenAPI / SQL boilerplate / mocks) | `jarvis-api/codegen.go` | n/a — generated artifacts must be hand-ported into Java equivalents | dropped (generator) / preserved (generated contract) | MEDIUM — Generated code drift is invisible until next regeneration. Capture a snapshot of the generated output that the monthly path depends on before deleting. |
| 15 | Tests covering `/monthly` (unit + integration + golden payloads) | jarvis-api `**/*_test.go` for monthly handler & service (unverified — not yet observed in partial scan) | skalbox-api JUnit5 + MockMvc tests (per AC #6) | changed (re-written) | **HIGH** — A test re-write is not a parity proof. Mandatory: capture jarvis-api `/monthly` golden responses against fixed inputs and replay them against skalbox-api in an integration test. Without this, behavior parity is asserted but not measured. |
| 16 | Postman / contract collection | (not in jarvis-api scan) | `skalbox-api/Skalbox-api.postman_collection.json` (referenced by SA) | preserved (must still pass) | LOW — only LOW if actively run in CI; otherwise MEDIUM (stale collection gives false assurance) |
| 17 | CI/CD pipeline & deployment manifests | `jarvis-api/build/ci/Jenkinsfile`, `jarvis-api/build/cd/Jenkinsfile`, `jarvis-api/build/cd/k8s/{dev,qa,prod}/app.yaml` | skalbox-api equivalents (not visible in available scan slice) | preserved (skalbox-api pipeline already exists) — jarvis-api side **must not be decommissioned in this PR** if other endpoints still live there | MEDIUM — Premature jarvis-api decommissioning is a known footgun. Confirm jarvis-api still has non-monthly traffic before any teardown. |

---

## Summary of HIGH-Risk Silent-Change Candidates (action items)

1. **JSON serialization defaults** (row 6) — diff a sample monthly response from jarvis-api vs skalbox-api byte-for-byte.
2. **Timezone / month boundary** (row 4) — pin `ZoneId` explicitly in the new Java code; verify against jarvis-api's `time.Time` zone source.
3. **Numeric precision** (row 3) — confirm whether jarvis-api uses `float64` or any integer/rounded form; mirror exactly in Java (`BigDecimal` if currency).
4. **Validation semantics** (row 2) — re-run jarvis-api's edge-case inputs (empty params, zero dates, out-of-range months) against skalbox-api and confirm identical responses.
5. **Error envelope** (row 7) — diff status codes and error body keys for each known failure mode.
6. **Auth / scope** (row 10) — diff the filter chains; ensure no scope loosened.
7. **Config defaults** (row 12) — produce a mapping table of every jarvis-api env var the monthly path reads to its skalbox-api counterpart, with default values.
8. **DB migration ownership** (rows 5, 13) — explicitly document who owns the schema post-migration and how Flyway/Liquibase baselines.
9. **Resilience inheritance** (row 9) — if jarvis-api had retries on DB or downstream calls in its monthly handler, port them.
10. **Golden-payload regression test** (row 15) — non-negotiable; the only objective parity gate.

## Required Next Step

Grant read access on the two repo roots (or supply the full untruncated `migrate_from_scan` / `source_scan` payloads), then I can replace every **(unverified)** marker above with concrete file paths and line numbers, and convert each HIGH-risk row into a pass/fail finding rather than a watch-item.
