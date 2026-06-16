# Feature Brief

## Title
Migrate endpoint /monthly logic from jarvis-api into skalbox-api

## Why
Currently, the `/monthly` endpoint in `skalbox-api` is calling `jarvis-api` to process or retrieve related data.
The runtime dependency between `skalbox-api` and `jarvis-api` increases coupling between the two services, making deployment, debugging, and maintenance difficult, and potentially affecting performance or availability if `jarvis-api` encounters errors.
The goal of this task is to examine all code related to the `/monthly` endpoint in `skalbox-api`, identify the parts calling `jarvis-api`, and then migrate the necessary logic from `jarvis-api` to `skalbox-api` so that `skalbox-api` can handle it directly.

## Scope
- Analyze the `/monthly` endpoint in the `skalbox-api` repository.
- Identify the controller, service, client, DTO, mapper, config, repository, and classes related to `/monthly`.
- Find all code in `skalbox-api` that calls `jarvis-api`.
- Analyze the corresponding processing in `jarvis-api` that serves `/monthly`.
- Migrate the necessary logic from `jarvis-api` to `skalbox-api`.
- Replace the call flow from `skalbox-api` to `jarvis-api` with internal processing within `skalbox-api`.
- Maintain the current request/response contract of the `/monthly` endpoint, unless a clear error is detected that needs fixing.
- Migrate necessary DTOs/models/helpers/mappers/constants if they directly serve `/monthly`.
- Re-check validation, exception handling, logging, and error responses after migrating.
- Update or add unit tests/integration tests for the `/monthly` endpoint.
- Ensure code compiles and tests pass after migrating.

## Out of Scope
- Do not refactor the entire `skalbox-api` unless directly related to `/monthly`.
- Do not change business logic outside the scope of the `/monthly` endpoint.
- Do not change the API contract unless explicitly required.
- Do not migrate the entire `jarvis-api` to `skalbox-api`.
- Do not change the database schema unless absolutely necessary.
- Do not change the authentication/authorization flow if the current endpoint is working correctly.
- No deep performance optimizations beyond the necessary changes to remove the dependency to `jarvis-api`.

## Acceptance Criteria
- The `/monthly` endpoint in `skalbox-api` no longer calls the runtime to `jarvis-api`.
- The necessary logic previously located in `jarvis-api` has been migrated to `skalbox-api`.
- The `/monthly` request/response remains compatible with current behavior.
- Current success and error cases still work correctly.
- Code builds successfully.
- Unit tests or integration tests related to `/monthly` pass.
- No unnecessary dependencies are generated from `skalbox-api` to `jarvis-api`.
- Classes/clients/config used to call `jarvis-api` for `/monthly` are removed or no longer used if they do not serve other flows.
- There is suitable log to trace the `/monthly` processing flow after migration.

## Notes / Links
- Source repo: `skalbox-api`
- Legacy/source service: `jarvis-api`
- Target service: `skalbox-api`
- Endpoint to check: `/monthly`
- Main goal: eliminate `skalbox-api` calling `jarvis-api` for the `/monthly` flow