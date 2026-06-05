# Report

_Agent: `assistant` (General Assistant)_  
_Status: `success` · attempts: 1_

---

# Final Analysis Report — `/customer` Feature

**Prepared for:** Engineering Lead
**Scope:** `/customer` slice of `ubm-api` (3 Java files in scope: `AdminController.java`, `SAP.java`, `Permission.java`)
**Date:** 2026-06-04

---

## Overview

The `/customer` feature is an **administrative lookup endpoint** exposed by the `ubm-api` Spring Boot WebFlux service (`io.spdigital.ubm`, Singapore Power Digital — Utility Bill Management). It is **not** a customer-facing route — the full HTTP path is `GET /admin/customer?bpNo={bpNo}&userId={userId}`, registered in `AdminController.java:46`. A related listing endpoint `GET /admin/customers` (search by type/searchString with pagination) lives at `AdminController.java:36`.

The controller is intentionally thin: it accepts the two query parameters, delegates to `AdminService.getCustomer(bpNo, userId)`, and returns a `Mono<GetCustomerResponse>`. The underlying data source is the **SAP backend**, with the integration contract declared in `src/main/java/io/spdigital/ubm/service/sap/po/SAP.java` — specifically the endpoint constants `EBS_CUSTOMER_DETAILS_RETRIEVAL = "/CustomerDetailsRetrieval"` (line 20) and `CUSTOMER_PROFILE_RETRIEVAL = "/CustomerProfileRetrieval"` (line 26). Authorization metadata is carried via `common/enums/Permission.java`, indicating RBAC gating on the route (the specific permission constant is not visible in the truncated scan slice, but the enum's presence in scope is itself the signal).

Stack signals are unambiguous: **Spring WebFlux** (reactive `Mono<>` returns), **Lombok** for boilerplate reduction, **Jackson** with a custom `SnakeUpperCaseStrategy` for SAP wire compatibility, and a custom `@Loggable` aspect from `io.spdigital.ubm.logging` for structured cross-cutting audit logging.

---

## Architecture

### Layering

The feature follows a classic **layered Spring architecture with package-by-feature** on top:

| Layer | Component | File |
|---|---|---|
| Presentation (REST) | `AdminController` | `src/main/java/io/spdigital/ubm/admin/controller/AdminController.java` |
| Application service | `AdminService` (interface, inferred) | not in scoped slice |
| Integration contract | `SAP` (endpoint constants + DTOs) | `src/main/java/io/spdigital/ubm/service/sap/po/SAP.java` |
| Authorization metadata | `Permission` enum | `src/main/java/io/spdigital/ubm/common/enums/Permission.java` |
| Cross-cutting | `@Loggable`, `MaskingUtil`, `SnakeUpperCaseStrategy` | various |

### Request flow

```
HTTP GET /admin/customer?bpNo=…&userId=…
   │  @Loggable (audit / structured log)
   ▼
AdminController.getCustomer(bpNo, userId)     ← AdminController.java:46
   ▼
AdminService.getCustomer(bpNo, userId) : Mono<GetCustomerResponse>
   ▼
SAP integration → /CustomerDetailsRetrieval, /CustomerProfileRetrieval (SAP.java:20, :26)
   ▼
GetCustomerResponse (PII masked on egress via MaskingUtil + Jackson SnakeUpperCaseStrategy)
```

### Architectural posture

- **Reactive end-to-end** is implied (`Mono<>` all the way down); this is consistent with non-blocking SAP I/O but only delivers value if the downstream SAP client is also non-blocking (e.g., `WebClient`). That cannot be verified from the scoped slice.
- **Thin controller / fat service** — sound separation of concerns; presentation does no business logic.
- **Package-by-feature for `admin`** (controller + service + dto colocated) **mixed with package-by-layer for shared modules** (`common`, `model.dto`, `logging`). This is a common, workable hybrid but invites drift if not enforced.
- **SAP as a hard external dependency** — the route's availability is bounded by SAP availability. No evidence of caching, circuit breaker, or fallback in the scoped files.

---

## Quality & Risk

### Strengths

1. **Clear separation of concerns** — controller delegates immediately; SAP contract is isolated in a dedicated package (`service.sap.po`).
2. **PII handling is on the radar** — `MaskingUtil` and a SAP-specific Jackson naming strategy indicate the team has thought about sensitive payloads at the serialization boundary.
3. **Cross-cutting audit logging via `@Loggable`** — uniform structured logs are a strong base for an admin endpoint that will need traceability.
4. **RBAC integration via `Permission` enum** — gating administrative customer lookups behind a typed permission constant is the right shape.

### Risks & smells

1. **Mixed Jackson packages (architect flagged as smell #3)** — imports referenced `tools.jackson.databind` alongside `com.fasterxml.jackson.*`. The `tools.jackson` namespace belongs to **Jackson 3.x**; `com.fasterxml.jackson` is **Jackson 2.x**. Coexistence in one codebase is almost always a migration artifact and a source of subtle serialization bugs (two ObjectMappers, two annotation processors, divergent behaviour). **High-priority fix.**
2. **No visible resilience around SAP calls** — the scoped files reveal no timeout, retry, circuit breaker, or bulkhead config. For an admin lookup that fans out to two SAP endpoints (`/CustomerDetailsRetrieval`, `/CustomerProfileRetrieval`), a SAP slowdown will tie up reactor threads and propagate latency. Unverified in scope, but worth confirming.
3. **Admin route under `/admin/**` with two query-string identifiers (`bpNo`, `userId`)** — both look like sensitive identifiers. Confirm: (a) the route is behind an authenticated/authorized filter chain, (b) `bpNo`/`userId` are not logged in plaintext by `@Loggable` or access logs, (c) the `Permission` gate is actually enforced (annotation-only checks are easy to miss if a filter doesn't read them).
4. **Truncated inputs in upstream scan** — `SAP.java` and `Permission.java` were not fully captured. Notable unknowns: which exact `Permission` constant gates `/customer`, and the full SAP DTO shape for `GetCustomerResponse`. The lead should be aware that conclusions about authorization and payload structure are inferred, not verified.
5. **No tests in scope** — the inventory contains zero test files for the `/customer` slice. Whether tests exist outside the filtered scope is unknown, but the lead should treat the absence as a finding to verify.
6. **Build/config not in scope** — `pom.xml`/`build.gradle` and `application.yml` were excluded, so dependency versions (notably Spring Boot, Reactor, Jackson) and externalized SAP endpoints/timeouts cannot be confirmed.

---

## Recommended Next Steps

Ordered by impact:

1. **Resolve the Jackson 2.x / 3.x mixed-imports issue.** Audit `AdminController.java` and `SAP.java` imports, pick one Jackson major version, and remove the other. This is the single highest-leverage cleanup — it eliminates a whole class of latent serialization bugs.
2. **Verify authorization end-to-end on `GET /admin/customer`.** Confirm which `Permission` constant gates the route in `Permission.java`, that it is actually enforced (not just declared), and that the SecurityContext propagation works under WebFlux's reactive context (a common foot-gun: `SecurityContextHolder` doesn't work in reactive flows — must use `ReactiveSecurityContextHolder`).
3. **Confirm PII masking covers logs, not just responses.** Inspect `@Loggable` and any access-log config to ensure `bpNo` and `userId` are masked or omitted from log lines — the response-side `MaskingUtil` only protects the egress payload.
4. **Add resilience to the SAP integration.** Validate that the SAP `WebClient` (or equivalent) has explicit connect/read timeouts, a circuit breaker (Resilience4j is the typical Spring choice), and a sensible retry policy that distinguishes idempotent reads (`/CustomerDetailsRetrieval`) from anything that mutates.
5. **Expand the scan and add tests.** Pull `AdminService`, the SAP client implementation, `application.yml`, and `pom.xml`/`build.gradle` into scope, then ensure there is at least: one `@WebFluxTest` slice for `AdminController.getCustomer`, one contract test against the SAP DTO, and one integration test that exercises the `Permission` gate (positive + negative cases).
6. **Decide on caching.** Customer profile reads from SAP are good candidates for short-TTL caching keyed on `bpNo` — discuss with the team whether staleness is acceptable for the admin use case before implementing.
7. **Document the admin contract.** A short OpenAPI/Swagger entry for `GET /admin/customer` (parameters, required permission, response shape, masked fields) closes the loop for downstream admin-UI consumers.

---

**Caveat to the lead:** This report is bounded by a 3-file pre-filtered slice. Items 2, 3, 4, and 5 above contain verifications that may already be satisfied elsewhere in the codebase — the recommendation is to *confirm*, not necessarily to *implement from scratch*.
