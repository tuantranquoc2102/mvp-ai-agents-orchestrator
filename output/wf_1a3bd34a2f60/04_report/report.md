# Report

_Agent: `assistant` (General Assistant)_  
_Status: `success` · attempts: 1_

---

# Final Analysis Report — Supermarket Management System (QLST_12)

**Prepared for:** Engineering Lead
**Date:** 2026-06-03
**Scope:** Legacy Java Servlet/JSP web application (~5.3 MB, 50 files) located at `F:\03_POC_PROJECTS\Supermarket-Management-System_JavaServerlet_JSP`

---

## 1. Overview

QLST_12 ("Quản Lý Siêu Thị" — Supermarket Management) is a small academic-grade Java EE web application, almost certainly a PTIT coursework deliverable. It is built with NetBeans + Ant (`QLST_12/build.xml`, `QLST_12/nbproject/build-impl.xml`) and packaged as a WAR. The codebase comprises three loosely structured layers:

- **Presentation:** 13 JSPs under `QLST_12/web/` using a `GD*` (Giao Diện) naming convention, with shared fragments `Header726.jsp`, `Footer726.jsp`, `Menu726.jsp`, `MenuQL726.jsp`. Likely entry points are `Trangchu726.jsp` (home), `GDDangNhap726.jsp` (login), `GDDangky726.jsp` (registration), and `GDQL726.jsp` / `MenuQL726.jsp` (admin console).
- **Data access:** 6 DAO classes in `QLST_12/src/java/DAO726/` (`DAO726`, `HDTT_DAO726`, `HoadonMua_DAO726`, `KH_DAO726`, `NVQL_DAO726`, `TKKH_DAO726`) using raw JDBC.
- **Domain (anemic):** 13 POJOs in `QLST_12/src/java/Entity726/` covering customers (`KhachHang`, `TKKH`), staff roles (`NVBH`, `NVGH`, `NVK`, `NVQL`), products (`MatHang`), invoices (`HoaDonMua`, `HDTrucTiep`), suppliers (`NhaCungCap`), and the store entity (`SieuThi`).

Supporting artifacts: `README.md`, `LICENSE`, and a Vietnamese SA/SD document (`Phân tích thiết kế hệ thống.pdf`). UI branding is in `web/css/` and `web/image/`.

**Headline finding:** No Servlet, Controller, Service, Filter, or `web.xml` was surfaced in the inventory. This points strongly to a **Model 1 (JSP-scriptlet-driven)** architecture rather than Model 2 MVC. A `web/WEB-INF/web.xml` may exist but is not in the expanded listing and should be verified before final disposition.

---

## 2. Architecture

**Style:** Classic JSP/Servlet Model 1 / thin 3-tier legacy Java EE, deployed to Tomcat or GlassFish per `QLST_12/nbproject/ant-deploy.xml`.

**Flow (inferred):** JSP → DAO → JDBC → RDBMS, with anemic POJOs as data carriers. Domain logic, validation, authn/authz, and transaction control most likely live inside JSP scriptlets — the most fragile location possible for business rules.

**Module map:**

| Layer | Location | Responsibility |
|---|---|---|
| View | `QLST_12/web/*.jsp` (13 files) | Rendering + (likely) request handling via scriptlets |
| View fragments | `Header726.jsp`, `Footer726.jsp`, `Menu726.jsp`, `MenuQL726.jsp` | Layout includes |
| Static assets | `web/css/`, `web/image/` | Styling, PTIT branding |
| Data access | `QLST_12/src/java/DAO726/` (6 files) | JDBC CRUD per aggregate root |
| Domain | `QLST_12/src/java/Entity726/` (13 files) | Anemic getter/setter POJOs |
| Build/config | `QLST_12/nbproject/`, `build.xml`, `src/conf/MANIFEST.MF` | Ant build, NetBeans descriptors, deploy targets |

**Aggregate coverage gap:** Entities exist for 13 concepts but only 5 DAOs exist beyond the base `DAO726`. There is no DAO for `MatHang`, `NhaCungCap`, `SieuThi`, `NVBH`/`NVGH`/`NVK`, or `HDTrucTiep` (despite `HDTT_DAO726` likely mapping to it). Either the JSPs query these entities inline, or major CRUD paths are unimplemented.

**External dependencies:** RDBMS over JDBC (driver and URL not visible in the inventory — likely hard-coded in `DAO726`). No ORM, no connection pool indicator, no DI framework.

---

## 3. Quality & Risk

### Architecture-level risks
- **Model 1 anti-pattern.** Business logic embedded in JSP scriptlets makes the app effectively untestable, hard to refactor, and prone to view/domain coupling. Any rule change requires editing a JSP.
- **No service layer.** Transaction boundaries, authorization checks, and cross-aggregate workflows (e.g., creating an invoice that decrements stock in `MatHang`) have no natural home.
- **Anemic domain.** All 13 entities in `Entity726/` appear to be getter/setter shells, so invariants cannot be enforced at the domain level.

### Security risks (high severity given handling of accounts and invoices)
- **SQL injection** is the default outcome of hand-rolled JDBC unless `PreparedStatement` is used consistently. The presence of `TKKH_DAO726` (customer account DAO) and a login screen (`GDDangNhap726.jsp`) makes this the single most urgent item to verify.
- **Credential storage.** `TKKH` (account) likely stores plaintext passwords; no hashing/salt utility is visible.
- **Session/auth.** No `Filter` or `web.xml` surfaced means there is probably no centralized authentication enforcement — pages are protected (if at all) by ad-hoc session checks in scriptlets.
- **XSS.** JSPs without JSTL `<c:out>` or EL escaping in scriptlets will reflect user input verbatim.
- **CSRF.** No tokenization mechanism is implied by the structure.

### Code-quality risks
- **Naming.** The `726` suffix on every class/file (`DAO726`, `Entity726`, `Header726.jsp`, …) is a course-section tag, not a versioning or module discriminator — it carries no engineering value and bloats every identifier.
- **Vietnamese-only identifiers** (`KhachHang`, `HoaDonMua`, `NhaCungCap`) are fine for a local academic team but will impede onboarding of non-Vietnamese contributors or static-analysis tooling tuned for English.
- **Build system.** Ant + NetBeans project metadata (`nbproject/build-impl.xml`, `genfiles.properties`) is essentially unmaintained in modern Java ecosystems. No dependency manifest (no `pom.xml`, no `build.gradle`) means dependency versions and CVEs are invisible.
- **No tests.** Inventory shows zero test files (`src/test`, `*Test.java`).
- **No CI/CD signal.** No workflow files, Dockerfile, or deployment scripts beyond NetBeans' `ant-deploy.xml`.

### Operational risks
- The application very likely will not run unmodified on a current Java 21 / Jakarta EE 10 stack (`javax.*` → `jakarta.*` rename, removed APIs).
- JDBC credentials are presumed hard-coded in `DAO726`; no environment-based config is visible.

---

## 4. Recommended Next Steps

The right answer depends on whether this is being treated as a **museum piece** (preserve as portfolio/learning artifact) or a **product candidate** (evolve into something deployable). I recommend the following triage in priority order:

### Immediate (1–2 days) — confirm the unknowns before any further investment
1. **Read `QLST_12/web/WEB-INF/web.xml`** (if present) and any `*Servlet.java` not surfaced in the inventory — settles the Model 1 vs Model 2 question and reveals the auth/filter chain.
2. **Open `QLST_12/src/java/DAO726/DAO726.java`** to confirm JDBC driver, connection URL, and — critically — whether queries use `PreparedStatement` or string concatenation. This single file determines the SQLi blast radius.
3. **Open `QLST_12/src/java/DAO726/TKKH_DAO726.java`** and `GDDangNhap726.jsp` to confirm how passwords are stored and verified.
4. **Inspect `Phân tích thiết kế hệ thống.pdf`** for the intended ER diagram and use cases — invaluable for any modernization scope.

### Short term (1–2 weeks) — if the project will continue
5. **Introduce a controller layer.** Extract scriptlet logic from each `GD*.jsp` into Servlets (or jump to Spring MVC) so JSPs become pure views. Start with `GDDangNhap726.jsp` because it carries the auth risk.
6. **Parameterize every query** in `DAO726` and subclasses. Add a `PreparedStatement`-only review checkpoint.
7. **Hash passwords** (BCrypt) in `TKKH_DAO726`; add a one-time migration for existing rows.
8. **Add a build manifest.** Migrate `build.xml` → Maven (`pom.xml`) so dependencies (JDBC driver, JSTL, BCrypt, JUnit) are tracked and CVE-scannable.
9. **Fill the DAO gaps.** Create DAOs for `MatHang`, `NhaCungCap`, `HDTrucTiep`, and the missing staff roles so JSPs stop talking to JDBC directly.
10. **Centralize auth** via a Servlet `Filter` mapped in `web.xml`; remove per-page session checks.

### Medium term (1–2 months) — modernization, only if scope justifies it
11. **Target Jakarta EE 10 / Java 21.** Rename `javax.servlet` → `jakarta.servlet`, retarget the WAR to Tomcat 10+.
12. **Introduce JUnit 5** and a minimum smoke-test suite around DAOs (Testcontainers for the DB) and one happy-path login flow.
13. **Drop the `726` suffix** project-wide and standardize on English package names alongside the Vietnamese domain terms (`Entity726.KhachHang` → `domain.customer.Customer`).
14. **Add a Dockerfile and a GitHub Actions pipeline** (build → test → CodeQL/Dependency-Check → publish WAR).

### If the project is **not** continuing
- Keep as-is, but add a `SECURITY.md` flagging the SQLi/plaintext-password risk so no one redeploys this to a public host, and archive the repository read-only.

---

**Bottom line:** This is a textbook Model 1 JSP/Servlet codebase with the textbook risks — SQL injection, plaintext credentials, no tests, dead build tooling. It is salvageable, but the modernization cost (controllers, Maven, Jakarta EE, auth filter, hashed passwords, tests) is comparable to rewriting the same feature set on Spring Boot 3. Before committing to either path, validate the three files in step 1–3 above; they will tell you in an hour whether this is a security incident waiting to happen or merely an outdated but contained learning artifact.
