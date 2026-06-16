# Rationale

_Agent: `architect` (Software Architect)_  
_Status: `success` · attempts: 1_

---

I drafted the change-rationale document but the write was blocked pending permission. Once you approve writing to `F:\02_SPG_PROJECTS\skalbox-api-jarvis-api-month-chart\skalbox-api\docs\changes\2026-06-08-migrate-endpoint-monthly-logic-from-jarvis-api-i.md`, I'll create it. Below is the draft for review.

---

**Path:** `docs/changes/2026-06-08-migrate-endpoint-monthly-logic-from-jarvis-api-i.md` (in `skalbox-api`)

**Structure:**
- **Header** — date, slug, branch, source/target repos and tech stack, Jira (N/A).
- **§1 Why** — business motivation (remove SPOF, consolidate ownership, kill an inter-service hop, simplify ops) + technical motivation (thin-proxy elimination, drop retry/CB/TLS surface, better testability, cleaner package layout under `io.spdigital.skalbox.monthly.*`).
- **§2 What changes** — controller (contract preserved), service (logic ported in-process), DTO/model/mapper port, outbound Jarvis client removal, config cleanup, cross-cutting logging, tests, build/postman.
- **§3 Out of scope** — contract changes, broader refactors, other endpoints, full jarvis-api migration, schema changes, auth redesign, perf tuning, jarvis-api decommissioning, doc rewrites.
- **§4 Acceptance criteria** — 10 numbered items mirroring the BA brief, plus build/test/postman/observability/docs gates.
- **§5 Logic-parity checklist** — required for cross-service migration. Ten sub-tables (API contract, validation, authn/z, data retrieval, business logic, response shaping, error handling, observability, config/deploy, testing) with each row marked **preserved / changed / deprecated** and `(verify)` flags on rows that still need confirmation against actual `jarvis-api` source.
- **Verification gates before merge** + **Open questions / risks** (repo ownership, time-zone parity, rounding parity, shared Jarvis client, dashboards).

Please grant write permission for that path (or tell me a different path) and I'll commit the file.
