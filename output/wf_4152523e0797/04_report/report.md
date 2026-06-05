# Report

_Agent: `assistant` (General Assistant)_  
_Status: `success` · attempts: 1_

---

# Final Analysis Report — `/customer` Feature (`ubm-api`)

## Overview

The `/customer` feature is the customer-management surface of the `ubm-api` Spring Boot service (root package `io.spdigital.ubm`). It is scoped to **50 Java source files (~125 KB)** under `src/main/java/io/spdigital/ubm/`, with no test files in scope. The feature is **read-oriented and admin-facing**, fronted by `admin/controller/AdminController.java` (e.g. `GET /admin/customers`), with secondary touchpoints in `approvals/controller/ApprovalController.java`. Customer data is sourced from SAP via `service/sap/SAPServiceImpl.java`, and the slice carries the full set of cross-cutting concerns the platform requires: Auth0-based authentication, URL-level permission enforcement, audit logging, PII masking, and structured request/response logging.

Beyond pure read, the DTO surface (`admin/dto/GetCustomerResponse`, `Subscription`, `UpdateBpNo`, `ForgotPassword`) signals that the feature also covers **subscription detail retrieval, Business Partner (BP) number updates, and a forgot-password flow** — endpoints likely defined further down `AdminController` than the truncated snippet exposed.

## Architecture

**Layering (top → bottom) for the customer slice:**

| Layer | Representative files |
|---|---|
| HTTP edge | `admin/controller/AdminController.java`, `approvals/controller/ApprovalController.java` |
| Application service | `admin/service/AdminService.java`, `admin/service/UserService.java` + `impl/` |
| Integration / outbound | `service/sap/SAPServiceImpl.java`, `service/sap/po/SAP.java` |
| Supporting domain services | `service/audit/*` (5 files), `service/notifications/*` (3), `service/holidays/*` (2) |
| Cross-cutting | `config/SecurityConfiguration`, `config/Auth0Configuration`, `config/PermissionFilter`, `config/CorsConfig`/`CorsProperties`, `config/WebClientConfiguration`, `config/ProxyProperties`, `config/ConnectionProperties`, `config/SentryConfig`, `logging/LoggableAspect` + `LogMasking`, `web/RequestLoggingFilter`, `util/MaskingUtil` |
| Shared types | `common/Permission`, `common/SkipURLPermission`, `common/SecurityContextHeader`, `common/Utility`, `common/YesOrNo`, `common/OnOrNo` |
| Errors | `exception/UbmApiException`, `exception/NotFoundException` |

**Runtime model.** The controller returns `Mono<SearchCustomers.Response>` and imports `reactor.core.publisher.Mono`, indicating Spring **WebFlux** at the edge, with `WebClientConfiguration` providing a reactive outbound client to SAP. The canonical request/response contract (`SearchCustomers.Response`) lives in `io.spdigital.ubm.model.dto.Yggdrasil` — i.e., **an external shared library outside this repo** — while local DTOs in `admin/dto/` are admin-side projections layered on top.

**Security and access control.** Edge auth is Auth0 (`config/Auth0Configuration`, `config/SecurityConfiguration`); per-URL enforcement is handled by `config/PermissionFilter` driven by the `common/Permission` and `common/SkipURLPermission` enums, with `common/SecurityContextHeader` propagating principal context downstream.

**Observability.** A `@Loggable` AOP annotation (`logging/LoggableAspect`) wraps the customer endpoint; `logging/LogMasking` + `util/MaskingUtil` redact PII; `web/RequestLoggingFilter` captures request/response envelopes; `config/SentryConfig` ships errors to Sentry.

**Audit.** Customer mutations (BP update, forgot-password) flow through `service/audit/` (`AuditType`, `AuditConstants`, `Audit` DTO), giving the feature a dedicated audit trail distinct from generic logging.

## Quality & Risk

1. **Reactive/servlet mixing in the controller (architectural smell).** `AdminController.java` imports both `reactor.core.publisher.Mono` *and* `org.springframework.web.servlet.function.ServerResponse` (a servlet-world type). On WebFlux this is at best dead code; at worst it indicates copy-paste from a servlet template or a half-finished migration. This needs to be reconciled — WebFlux apps should not surface servlet `ServerResponse` types.

2. **No tests in scope.** Zero test files were returned for the feature filter across `AdminController`, `AdminServiceImpl`, `SAPServiceImpl`, the audit chain, or `PermissionFilter`. The customer surface owns auth, audit, masking, and an external SAP dependency — exactly the surface that most needs unit + integration coverage. This is the single largest risk in the slice.

3. **External contract coupling to `Yggdrasil`.** The controller's response type (`SearchCustomers.Response`) is owned by an out-of-repo shared library. Versioning, breaking-change discipline, and source-of-truth ownership for that contract are invisible from this repo, so any change to customer payloads is a cross-repo coordination problem rather than a local one.

4. **SAP as a hard runtime dependency.** `GET /admin/customers` ultimately fans out to SAP via `SAPServiceImpl`. There is no resilience pattern (circuit breaker, bulkhead, retry budget) visible in the file inventory — `config/ConnectionProperties` and `config/ProxyProperties` look like raw client tuning, not failure isolation. A slow or down SAP will propagate latency directly to admin users.

5. **Permission model is enum-driven and centralized.** `common/Permission` + `common/SkipURLPermission` enforced by `config/PermissionFilter` is simple and auditable, but enum-based permission lists are change-heavy: every new endpoint requires an enum edit + filter update, which is easy to forget for a `/customer` sub-route and can silently widen access.

6. **PII handling depends on annotation discipline.** `logging/LogMasking` + `util/MaskingUtil` only mask what `@Loggable`/the masking config knows about. With customer DTOs containing names, BP numbers, subscription detail, and forgot-password payloads, any new field added to `admin/dto/GetCustomerResponse`, `Subscription`, or `ForgotPassword` is unmasked by default — a leak waiting to happen.

7. **Audit coverage is asymmetric.** `service/audit/` is wired for mutations, but the read endpoint (`GET /admin/customers`) — which exposes the most customer data — is the one most worth auditing for admin-access compliance. It's unclear from the inventory whether reads emit audit events; this should be confirmed.

8. **Truncated controller view.** The inventory shows the `customers` match on lines 36 and 46 of `AdminController`, implying multiple customer routes that weren't fully visible. Any sign-off on this feature should be gated on reading the complete controller, not the snippet.

## Recommended Next Steps

1. **Resolve the WebFlux/servlet mix in `admin/controller/AdminController.java`.** Remove the `org.springframework.web.servlet.function.ServerResponse` import (and any usage) or, if the project is actually servlet-MVC and `Mono` is the anomaly, decide one stack and migrate. Don't ship the hybrid.

2. **Stand up a test baseline for the slice.** Minimum: WebFlux slice tests for `AdminController` (happy path + 401/403 via `PermissionFilter`), a unit test for `AdminServiceImpl` with `SAPServiceImpl` mocked, and a contract test pinning the shape of `Yggdrasil.SearchCustomers.Response` so upstream library bumps fail loudly.

3. **Add resilience around SAP calls in `service/sap/SAPServiceImpl.java`.** Wrap the WebClient call with timeouts, a circuit breaker (Resilience4j integrates cleanly with Reactor), and a bounded retry. Surface SAP outages as a typed `UbmApiException` rather than a leaked WebClient error.

4. **Audit the read path.** Confirm whether `GET /admin/customers` emits a `service/audit/AuditType` event. If not, add one — admin reads of customer data are typically in scope for compliance audit, not just writes.

5. **Tighten PII defaults.** Change `logging/LogMasking` / `util/MaskingUtil` from opt-in (mask listed fields) to opt-out (mask all fields on flagged DTOs unless explicitly allow-listed). Apply the flagged DTO marker to `admin/dto/GetCustomerResponse`, `Subscription`, `UpdateBpNo`, and `ForgotPassword`.

6. **Decouple permission registration from the enum.** Either generate `common/Permission` entries from a declarative source (annotation on the controller method, or a config file checked at startup), or add a startup assertion in `config/PermissionFilter` that every mapped customer route has an explicit `Permission` or `SkipURLPermission` entry — fail fast on missing coverage.

7. **Document the `Yggdrasil` contract boundary.** A short README in `admin/controller/` (or a package-info) noting which response types come from the external library, where it's versioned, and the upgrade process. This is the kind of cross-repo coupling that bites new engineers first.

8. **Re-read the full `AdminController` before sign-off.** The truncated view almost certainly hides additional customer routes (subscription detail, BP update, forgot-password) whose risk profile differs from the listing endpoint — particularly the mutation routes, which need explicit review for CSRF posture, idempotency, and audit emission.
