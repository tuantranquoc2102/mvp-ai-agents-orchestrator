# Architecture

_Agent: `architect` (Software Architect)_  
_Status: `success` · attempts: 1_

---

I cannot read files outside the session's allowed working directory (`F:\03_POC_PROJECTS\claude`), and the embedded `codebase_scan` content was truncated mid-file. So this analysis is bounded to: the file list (50 paths), the visible `AdminController` snippet, file sizes, and naming conventions. Anything I'm inferring rather than confirming is marked **[inferred]**.

# Architecture Analysis — `/customer` feature in `ubm-api`

## 1. Tech baseline (confirmed from snippet)

- **Language / runtime:** Java, Spring Boot.
- **Web stack:** Spring **WebFlux** — the controller method returns `Mono<SearchCustomers.Response>` and uses `reactor.core.publisher.Mono`. There is also `org.springframework.web.servlet.function.ServerResponse` imported (servlet-world type) — see smell §6.
- **Root package:** `io.spdigital.ubm`.
- **Shared model module:** `io.spdigital.ubm.model.dto.Yggdrasil` is referenced but lives outside this scan's file list, indicating an **external shared library** (likely "Yggdrasil") that owns the canonical customer request/response contracts (`SearchCustomers.Response`, etc.). The local DTOs (`GetCustomerResponse`, `Subscription`, `UpdateBpNo`) are admin-side projections layered on top.
- **Tooling visible:** Lombok (`@RequiredArgsConstructor`, `@Slf4j`), SLF4J, a custom `@Loggable` AOP annotation.

## 2. Layering for the `/customer` slice

```
HTTP edge        ─►  admin/controller/AdminController                (GET /admin/customers, …)
                     approvals/controller/ApprovalController         (also references /customer)
                          │
Cross-cutting    ─►  web/RequestLoggingFilter, logging/Request|ResponseLoggingDecorator,
                     logging/LoggableAspect (@Loggable), logging/LogMasking, util/MaskingUtil
                          │
Security gate    ─►  config/SecurityConfiguration, config/Auth0Configuration,
                     config/PermissionFilter, common/SecurityContextHeader,
                     common/enums/Permission, common/enums/SkipURLPermission
                          │
Application      ─►  admin/service/AdminService     (+ impl/AdminServiceImpl)
                     admin/service/UserService      (+ impl/UserServiceImpl)
                          │
Domain/DTO       ─►  admin/dto/{GetCustomerResponse, Subscription, UpdateBpNo, ForgotPassword}
                     io.spdigital.ubm.model.dto.Yggdrasil.SearchCustomers   ← external module
                          │
Downstream       ─►  service/sap/SAPServiceImpl + po/SAP            (system of record — SAP)
                     service/audit/AuditServiceImpl + dto/Audit     (audit trail)
                     service/notifications/NotificationBannersServiceImpl
                     service/holidays/HolidaysServiceImpl
                     service/TestServiceImpl
                          │
Outbound config  ─►  config/WebClientConfiguration                  (reactive HTTP client)
                     config/{ConnectionProperties, ProxyProperties, CorsConfig/CorsProperties,
                              SecurityProperties, SentryConfig}
                          │
Errors           ─►  exception/{UbmApiException, NotFoundException}
```

This is a **classic Spring layered architecture** (Controller → Service → outbound WebClient), not Hexagonal/Clean/DDD — there are no `domain`, `port`, `adapter`, `repository`, or `usecase` packages, and no aggregate roots.

## 3. How the `/customer` request flows (confirmed where snippet shows it)

1. **HTTP in** — `GET /admin/customers?type=…&searchString=…&pageNumber=…&pageSize=…&direction=…` hits `AdminController.getCustomers(...)` with `@Loggable`.
2. **Filter chain** — `RequestLoggingFilter` (logging/masking), Spring Security filters configured by `SecurityConfiguration` + `Auth0Configuration` (JWT/Auth0 **[inferred from file name]**), then `PermissionFilter` cross-checks the caller's `Permission` against the request, with `SkipURLPermission` enumerating bypassed paths.
3. **Service dispatch** — `AdminServiceImpl.getCustomers(...)` (and `UserServiceImpl` for adjacent user/customer ops). `AdminController` already holds both `adminService` and `userService` as collaborators.
4. **Downstream call** — `SAPServiceImpl` (using `WebClientConfiguration`, with proxy/connection properties) calls SAP for the actual customer search; `service/sap/po/SAP.java` carries the SAP payload objects. **[inferred from naming + reactive return type]**
5. **Side effects** — `AuditServiceImpl` writes an `Audit` record (`AuditType`, `AuditConstants`); `NotificationBannersServiceImpl` and `HolidaysServiceImpl` may decorate the response with banners/holiday context.
6. **Response** — Mapped into `Yggdrasil.SearchCustomers.Response` (search) or `GetCustomerResponse` (per-customer detail). Logging decorators serialise the response, applying `LogMasking`/`MaskingUtil` for PII.

`ApprovalController` shows up in the `/customer` scan too — approval workflows reference customer identifiers (likely an "approve customer change" path). Worth confirming whether it depends on `AdminService` or duplicates customer lookup logic.

## 4. External dependencies / boundaries

| Boundary | Component | Notes |
|---|---|---|
| Identity | Auth0 (`Auth0Configuration`, `SecurityProperties`) | OIDC/JWT validation |
| System of record | **SAP** (`SAPServiceImpl`, `po/SAP`) | Reactive WebClient, proxy-aware |
| Shared contracts | `Yggdrasil` model module | External JAR; controllers depend directly on its DTOs |
| Observability | Sentry (`SentryConfig`), SLF4J + `@Loggable` aspect | Errors → Sentry, structured request logs |
| Edge | CORS (`CorsConfig`, `CorsProperties`) | Browser callers |

## 5. Module communication pattern

- **In-process, synchronous, reactive.** No message broker, no event bus, no Kafka/RabbitMQ artefacts in the file list. Services are wired by Spring DI and call each other directly; the only async is the Reactor pipeline over `WebClient` to SAP.
- **No persistence layer in this scan.** No `@Entity`, `Repository`, JPA, MyBatis, or Mongo files were matched — the customer feature appears to be a **pass-through to SAP** plus an audit write. Audit storage destination is not visible from the file list (could be DB-backed elsewhere or pushed to another service).

## 6. Structural smells / risks

1. **Servlet + Reactive type mixing.** `AdminController` imports `org.springframework.web.servlet.function.ServerResponse` while returning `Mono<…>`. Either the import is dead, or part of the app is servlet-stack and part is reactive — that combo is a known footgun (blocking calls on Netty event loop). Worth grepping the rest of the controller body and pom/build file.
2. **Anaemic "god" controller candidate.** `AdminController` already pulls in both `AdminService` and `UserService`, plus DTOs for customers, subscriptions, BP-number updates, and forgot-password (`ForgotPassword.java` sits in `admin/dto`). `/admin` is becoming a junk-drawer endpoint covering customers, users, subscriptions, and auth flows. Splitting into `CustomerController`, `SubscriptionController`, `UserAdminController` would clarify ownership and let `PermissionFilter` reason about narrower URL prefixes.
3. **Cross-feature coupling via the `Yggdrasil` shared DTO module.** Controllers depend on `Yggdrasil.SearchCustomers.Response` directly — there is no anti-corruption layer between the HTTP edge and the shared model. A breaking change in `Yggdrasil` ripples straight into clients of `/admin/customers`. Adding an admin-side response DTO (you already have `GetCustomerResponse` for the detail call — do the same for search) would isolate the boundary.
4. **No clear "customer" bounded context.** Customer-related code is fragmented across `admin/`, `approvals/`, and `service/sap/`. There is no `customer/` package owning the concept. If customer logic grows, this will spread further. A `customer/` module (controller + service + dto + sap-adapter) is the minimum cleanup.
5. **Permission model coupling.** `PermissionFilter` + `Permission` enum + `SkipURLPermission` enum means every new endpoint requires touching two enums and a filter — a known scaling pain. Annotation-based (`@PreAuthorize` / custom `@RequiresPermission`) would localise the rule with the handler.
6. **`UserServiceImpl` lives under `admin/service/impl/`** but is named generically — likely contains both admin-user and end-customer-user operations. Risk of double-purpose service. Confirm whether "user" here means *admin operator* or *end customer* before touching it.
7. **Audit on the request path.** If `AuditServiceImpl` writes synchronously inside the reactive pipeline (and especially if it hits a blocking JDBC driver), it will cap throughput of `/admin/customers`. Verify it's either non-blocking or off-loaded to `boundedElastic`.
8. **No tests in the scanned set.** Zero files under `src/test/**` were matched. Either the scan filter dropped them or there are no tests covering `/customer` flows — needs confirmation, but it's the highest-leverage risk.

## 7. What I could not verify (gaps for the implementer)

- Full bodies of `AdminServiceImpl`, `UserServiceImpl`, `SAPServiceImpl`, and `ApprovalController` — needed to confirm the SAP call shape, the audit write semantics, and whether `ApprovalController` re-implements customer lookup.
- Whether `AuditServiceImpl` is synchronous/blocking.
- Whether the project is truly WebFlux end-to-end or hybrid (the `ServerResponse` import is the tell).
- Persistence target for `Audit` (no repository/entity files in scan).
- Test coverage for the customer endpoints.

If you want me to go deeper, re-run the scan from inside the allowed working directory (or copy the relevant files there) so I can read the actual service bodies rather than infer from filenames.
