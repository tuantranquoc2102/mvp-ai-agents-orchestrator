# Frontend Plan

_Agent: `fe_dev` (Frontend Developer)_  
_Status: `success` · attempts: 1_

---

# Frontend Implementation Plan — `/monthly` Migration (jarvis-api → skalbox-api)

> **Scope reality check:** The architect's plan locks the public contract of `/monthly` as **unchanged** (method, path, request DTO, response DTO, status codes, error payloads). That means **this is a no-feature-change frontend deliverable**. The frontend's job is (a) verify nothing breaks, (b) absorb any base-URL/config drift if Jarvis was previously called directly from the client, and (c) tighten error UX while we're in the file. If we discover the frontend was calling `jarvis-api` directly anywhere, **that** becomes the real work — Section 8 covers it.
>
> Paths below are marked **(verify)** where I do not have read access and the developer must grep on first read.

---

## 1. Pre-flight Discovery (do first, before planning any edit)

Run these from the frontend repo root before touching code. Outputs decide which sections of this plan actually apply.

| Grep | Purpose |
|---|---|
| `grep -rE "['\"\\`].*?/monthly" src/` | Find every `/monthly` call site. |
| `grep -rE "jarvis" src/` (case-insensitive) | Confirm whether the FE ever talked to jarvis-api directly. |
| `grep -rE "VITE_.*API\|REACT_APP_.*API\|NEXT_PUBLIC_.*API" .env* src/` | Inventory all API base-URL envs. |
| `grep -rE "monthly\|Monthly" src/` | Find chart components, hooks, types, fixtures, tests bound to `/monthly`. |
| `grep -r "openapi\|swagger" .` | Locate any generated client that needs regen. |

**Output of discovery → fill in this table before writing code:**

- [ ] `/monthly` call sites: _list paths_
- [ ] Direct jarvis-api calls from FE: _yes/no_ (if yes, see §8)
- [ ] Base URL envs touching jarvis/skalbox: _list_
- [ ] Generated client present: _yes/no, tool_
- [ ] Components rendering monthly data: _list_

---

## 2. Components

No new components. Audit and lightly touch existing ones.

**Modify (verify each path):**
- `MonthlyChart` (or equivalent) — the consumer of `/monthly`. **(verify)** Likely under `src/features/monthly/` or `src/components/charts/`.
  - No prop changes. No render changes.
  - Verify it tolerates the **exact same** response shape it does today — the contract guarantees this, but we re-assert via tests.
- `MonthlyChart` loading state — confirm skeleton/spinner is wired (we may see slightly different latency profiles post-migration; UI must not flicker).
- `MonthlyChart` empty state — confirm copy renders when response is `[]` or all-zero (unchanged behavior, just re-verified).
- `MonthlyChart` error state — see §5 (copy) and §3 (state).

**Do not touch:** any other chart, table, or dashboard component. If discovery shows monthly data feeds more than one component, list them here and treat each the same way: assert-only, no logic change.

---

## 3. State Management

No state-shape changes. The migration is server-side.

**Verify per call site:**
- Query key / cache key for `/monthly` (React Query / SWR / Redux Toolkit Query — **verify which**) stays identical. Changing the key would invalidate cached data unnecessarily.
- Stale time / refetch interval unchanged.
- Error retry policy unchanged.
- If the FE uses optimistic updates anywhere on monthly data: **none expected** (it's a read endpoint), but confirm.

**One judgment call to make explicit:**
- If the backend cutover is staged (feature-flag or canary), the FE cache may briefly see responses from both old and new paths. Since the contract is identical, this is safe and **requires no FE change**. Document this in the PR description so reviewers don't worry about it.

---

## 4. API Calls

**Modify (only if discovery shows direct jarvis-api calls):**
- `src/api/client.ts` **(verify)** — if there's a `jarvisClient` axios/fetch instance separate from `skalboxClient`, **remove it** and route `/monthly` through `skalboxClient`. This is the one real diff this plan might produce.
- `src/api/monthly.ts` **(verify)** — the `getMonthly()` function. If it currently hits jarvis-api base URL, change to skalbox-api base URL. Request/response types stay byte-identical.

**Modify (always):**
- `.env.example`, `.env.development`, `.env.production` — remove `VITE_JARVIS_API_URL` (or equivalent) if it's only referenced by the `/monthly` flow. Leave it if anything else uses it; flag for a follow-up cleanup ticket.
- `src/api/types/monthly.ts` **(verify)** — re-generate or hand-verify TS types against the skalbox-api OpenAPI spec post-migration. **Expectation: zero diff.** A non-zero diff means the backend broke contract — stop and escalate.

**Do not modify:**
- Auth interceptors, retry middleware, request/response transformers — unchanged.
- Any other endpoint.

---

## 5. Copy

Only one place needs attention: the error message that surfaces when `/monthly` fails.

**Audit (verify path, likely `src/features/monthly/MonthlyChart.tsx` or an i18n file):**
- Current error copy probably says something generic like "Failed to load monthly data." That's fine and **stays**.
- **Do not** mention "Jarvis" or "Skalbox" in user-facing copy. If discovery turns up an error message referencing "Jarvis service unavailable" or similar, **rewrite it** to be service-agnostic: `"Unable to load monthly data. Please try again."`

**i18n files to check (verify):**
- `src/locales/en.json` → search for `jarvis`, `monthly`
- `src/locales/<other-locales>.json` → same

No new strings. No translation work expected.

---

## 6. Routing

No routing changes. `/monthly` is an API path, not a frontend route. The page that hosts `MonthlyChart` (likely `/dashboard` or `/reports/monthly` — **verify**) keeps its route, params, and guards.

---

## 7. Files to Create / Modify

### Create
- `src/features/monthly/__tests__/monthly.contract.test.ts` **(new)** — a contract test that loads the backend's baseline fixtures (the same JSON the architect's Step 0 produces under `skalbox-api/src/test/resources/monthly/baseline/`) and asserts the FE's response parser/types accept them without runtime error. Copy the fixtures into `src/features/monthly/__tests__/fixtures/` so the FE test isn't coupled to BE repo layout.
- `src/features/monthly/__tests__/fixtures/monthly-happy.json` **(new)** — copy from BE baseline.
- `src/features/monthly/__tests__/fixtures/monthly-error-validation.json` **(new)** — copy from BE baseline.
- `src/features/monthly/__tests__/fixtures/monthly-error-downstream.json` **(new)** — copy from BE baseline.

### Modify (conditional — only if discovery finds direct jarvis calls)
- `src/api/client.ts` **(verify)** — remove `jarvisClient`.
- `src/api/monthly.ts` **(verify)** — point `getMonthly()` at skalbox-api base URL.
- `.env.example`, `.env.development`, `.env.production` — remove `*_JARVIS_API_*` envs.
- `src/api/types/monthly.ts` **(verify)** — regen from new OpenAPI; expect zero diff.

### Modify (conditional — only if copy audit finds vendor names)
- `src/locales/en.json` (and other locales) — strip "Jarvis" references from user-facing strings.

### Modify (always)
- `src/features/monthly/MonthlyChart.test.tsx` **(verify)** — add an assertion that the component renders the architect's Step 0 happy-path fixture without error. This is the regression gate.

### Do not modify
- Any component, hook, route, or store unrelated to `/monthly`.
- Build config, CI config, lockfiles (unless an env var removal in `.env.example` is the only diff in a config file).

---

## 8. Branch — "FE was calling jarvis-api directly"

If discovery in §1 finds `jarvis` references in `src/api/*` or in env files **consumed by FE code**, the real work is here. Execution:

1. Confirm with BE: the skalbox-api `/monthly` cutover is deployed to the same environment the FE points at.
2. Replace `jarvisClient.getMonthly(...)` (or fetch URL) with the skalbox-api equivalent. Same path `/monthly`, same params, same response handling.
3. Remove the now-unused `jarvisClient` instance and its base-URL env.
4. Run the contract test from §7 against the new path.
5. Smoke-test the page in dev against a real skalbox-api instance before merging.

This is still a small diff — one client file, one or two API wrapper files, one env-var cleanup.

---

## 9. Acceptance Checklist (developer self-check before opening PR)

- [ ] Discovery grep results pasted into the PR description.
- [ ] Generated TS types for `/monthly` show zero diff against current main.
- [ ] Contract test loads all three BE baseline fixtures and passes.
- [ ] `MonthlyChart` renders happy-path fixture in test without console errors/warnings.
- [ ] No user-facing copy mentions "Jarvis."
- [ ] No `*_JARVIS_API_*` env var remains referenced by FE code (grep is clean).
- [ ] Manual smoke: load the monthly page in a dev build pointed at the skalbox-api branch; chart renders identically to main.
- [ ] PR description notes "API contract unchanged; FE diff is config/test only" (or, if §8 applied, lists the swapped call sites).

---

## 10. Out of Scope (call out explicitly to prevent scope creep)

- Redesigning the monthly chart, adding new dimensions, or changing aggregation granularity.
- Adding loading skeletons or empty-state illustrations where none exist today.
- Migrating other endpoints away from jarvis-api (separate tickets per endpoint).
- Bumping React Query / SWR / axios versions.
- Storybook stories for `MonthlyChart` (unless one already exists and breaks — then fix in place).
