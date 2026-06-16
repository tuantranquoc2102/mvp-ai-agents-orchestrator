# Intake

_Agent: `ba` (Business Analyst)_  
_Status: `success` · attempts: 1_

---

# Problem Statement: Migrate `/monthly` Endpoint Logic from jarvis-api into skalbox-api

**Jira Ticket:** N/A (no ticket id provided)

**Task Type:** Migration (jarvis-api → skalbox-api)

---

## Goal
Eliminate the runtime dependency from `skalbox-api` to `jarvis-api` for the `/monthly` endpoint by migrating all necessary processing logic into `skalbox-api`, so that `skalbox-api` can serve `/monthly` requests entirely on its own while preserving the current request/response contract and behavior.

---

## In Scope
- **Discovery in `skalbox-api`**: Locate the `/monthly` controller, service, client(s) that call `jarvis-api`, DTOs, mappers, config, repositories, and any related classes.
- **Discovery in `jarvis-api`**: Identify the endpoint(s)/handlers, services, DTOs/models, mappers, helpers, constants, and supporting code that serve the `/monthly` flow.
- **Logic migration**: Port the required processing logic from `jarvis-api` into `skalbox-api`, including DTOs/models/helpers/mappers/constants that directly serve `/monthly`.
- **Call-flow replacement**: Replace the outbound HTTP/client call from `skalbox-api` to `jarvis-api` with internal in-process logic in `skalbox-api`.
- **Cross-cutting concerns**: Re-verify validation, exception handling, logging, and error responses after migration; add appropriate trace logging for the new internal flow.
- **Cleanup**: Remove or mark unused the `jarvis-api` clients/config/classes that no longer serve any other flow after migration.
- **Testing**: Update or add unit/integration tests covering `/monthly` success and error paths.
- **Build & test gate**: Ensure the project compiles and `/monthly`-related tests pass.

---

## Out of Scope
- Broader refactoring of `skalbox-api` beyond what `/monthly` requires.
- Business-logic changes outside the `/monthly` endpoint.
- Public API contract changes for `/monthly` (unless an existing defect requires a fix).
- Wholesale migration of `jarvis-api` into `skalbox-api`.
- Database schema changes (unless strictly unavoidable).
- Auth/authz flow changes when the current endpoint behavior is correct.
- Deep performance optimization beyond what is needed to remove the `jarvis-api` dependency.

---

## Acceptance Criteria
1. The `/monthly` endpoint in `skalbox-api` makes **no runtime call** to `jarvis-api`.
2. All logic previously residing in `jarvis-api` and required by `/monthly` has been migrated into `skalbox-api`.
3. `/monthly` request and response shapes remain **backward compatible** with current behavior.
4. Existing success and error cases continue to work correctly (validation, exceptions, error payloads preserved).
5. The `skalbox-api` project **builds successfully**.
6. Unit and/or integration tests for `/monthly` **pass**.
7. No new or lingering unnecessary dependencies from `skalbox-api` to `jarvis-api` remain.
8. `jarvis-api` clients, configurations, and helper classes used solely for `/monthly` are **removed or unused** in `skalbox-api` (kept only if shared with other flows).
9. Appropriate log statements exist to **trace the `/monthly` processing flow** post-migration.

---

## Key References
- **Source/legacy service:** `jarvis-api` — `F:\02_SPG_PROJECTS\skalbox-api-jarvis-api-month-chart\jarvis-api`
- **Target service:** `skalbox-api` — `F:\02_SPG_PROJECTS\skalbox-api-jarvis-api-month-chart\skalbox-api`
- **Endpoint under change:** `/monthly`
- **Working branch:** `migration/migrate-endpoint-monthly-logic-from-jarvis-api-i`
