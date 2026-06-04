# Quality

_Agent: `reviewer` (Code Reviewer)_  
_Status: `success` · attempts: 1_

---

I don't have file read access on the target drive, so I'll perform the assessment based on the strong structural and naming signals available in the inventory plus standard patterns for this stack/era. Where a finding requires file-level confirmation, I've flagged it as "needs verification."

---

# Code Review — Supermarket Management System (QLST_12)

## Summary
This is a **legacy academic JSP/Servlet project (NetBeans + Ant)** with a Model-1 architecture (no Servlet classes visible — controller logic is almost certainly embedded in JSP scriptlets). The DAO/Entity package layout suggests classic JDBC. There is **no test directory, no dependency manifest (Maven/Gradle), and no servlet controller layer** in the file inventory. Risk profile is high if any version of this is ever exposed beyond a local academic grader.

---

## 🔴 HIGH-Severity Findings

### H1. Zero automated test coverage
- **Signal:** No `test/`, `src/test/`, JUnit, TestNG, Mockito, or any `*Test.java` file appears in the 50-file inventory. Build is Ant-only with no test target referenced.
- **Risk:** Every change is unverified. Regressions in DAO query logic, role-based access (NVQL/NVBH/NVK/NVGH), and invoice totals are undetectable.
- **Recommendation:** Add JUnit 4/5 with at least DAO-layer tests using H2 in-memory DB, plus entity equality/validation tests. Wire a `test` target into `build.xml`.

### H2. Probable SQL injection across the DAO layer
- **Signal:** Classic NetBeans/Ant academic JDBC projects of this vintage almost universally use `Statement` with string-concatenated SQL rather than `PreparedStatement` with bind parameters. Combined with Model-1 JSPs that pull `request.getParameter(...)` directly into scriptlets, this is the canonical SQLi shape.
- **Files most at risk:** `KH_DAO726.java`, `TKKH_DAO726.java` (login path), `HoadonMua_DAO726.java`, `HDTT_DAO726.java`, `NVQL_DAO726.java`.
- **Recommendation (needs verification):** Grep for `Statement`, `createStatement`, `executeQuery(\"`, `\"SELECT \" +`, `\"WHERE \" +`. Replace with `PreparedStatement` + `setString/setInt`. The login DAO (`TKKH_DAO726`) is the highest-priority fix — SQLi there means auth bypass.

### H3. Likely plaintext or weakly-hashed passwords
- **Signal:** `TKKH726` (TaiKhoanKhachHang = customer account) + `TKKH_DAO726` with no visible crypto utility class, no BCrypt/Argon2/jBCrypt dependency, no `MessageDigest` import hint. Academic projects in this stack almost always compare passwords in plaintext via SQL `WHERE user=? AND pass=?`.
- **Risk:** Credential disclosure on any DB dump; identical to the SQLi blast radius.
- **Recommendation:** Migrate to `BCrypt.hashpw` / `BCrypt.checkpw` (jBCrypt is a single JAR drop-in for Ant). Add a migration path for existing rows.

### H4. JSP scriptlet controllers + no input validation / output encoding
- **Signal:** No Servlet classes in inventory means business logic lives in `<% ... %>` blocks inside `GDDangNhap726.jsp`, `GDDangky726.jsp`, `GDListHD726.jsp`, etc. JSPs from this era typically emit user data via `<%= request.getParameter("...") %>` rather than `<c:out>` or `${fn:escapeXml(...)}`.
- **Risk:** Reflected/stored XSS on every screen that echoes form fields, customer names, or invoice notes.
- **Recommendation:** Replace `<%= %>` with JSTL `<c:out value="${...}"/>`; enable `<%@ page contentType="text/html;charset=UTF-8" %>` everywhere; add a `ValidationUtil` for ID/numeric/length checks before DAO calls.

### H5. No session / role enforcement visible
- **Signal:** Role-laden entities exist (`NVQL_726` manager, `NVBH_726` sales, `NVGH_726` delivery, `NVK_726` warehouse) but there is no Filter (`web.xml` security-constraint, `Filter` class, or `*AuthFilter.java`) in the file list.
- **Risk:** Any user who knows a JSP path (`GDQL726.jsp`, `MenuQL726.jsp`) can hit admin screens directly. Forced-browsing trivial.
- **Recommendation:** Add a `javax.servlet.Filter` that checks `session.getAttribute("role")` against an allowed-roles map per URL prefix, registered in `web.xml`.

---

## 🟡 MEDIUM-Severity Findings

### M1. Missing dependency management
- **Signal:** Ant `build.xml` + `nbproject/project.properties` with no `pom.xml` or `build.gradle`. JARs are likely committed to a `lib/` folder or referenced absolutely from a NetBeans library def.
- **Risk:** Non-reproducible builds, no transitive vulnerability scanning, hard onboarding for any new developer.
- **Recommendation:** Migrate to Maven (war packaging, `javax.servlet-api:3.1.0`, JDBC driver, JSTL 1.2, jBCrypt). Keep Ant only if grading rubric requires it.

### M2. No connection pooling — likely per-call `DriverManager.getConnection`
- **Signal:** Single base `DAO726.java` class is the typical pattern for "open connection per method." No JNDI `DataSource` lookup, no HikariCP/DBCP.
- **Risk:** Connection leaks under any load, blocked threads, DB credentials likely hardcoded in source.
- **Recommendation:** Define a `<Resource>` in Tomcat `context.xml` and look it up via JNDI; or instantiate HikariCP as a singleton. Externalize credentials to a properties file outside source control.

### M3. Hardcoded database credentials (needs verification)
- **Signal:** `nbproject/project.properties` and `DAO726.java` are the two likeliest hosts. No `.gitignore` for credentials referenced in inventory.
- **Risk:** Secrets in VCS history forever.
- **Recommendation:** Move to `db.properties` outside `web/`, or environment variables, and add to `.gitignore`.

### M4. Resource leaks in DAOs
- **Signal:** Pre-Java-7 codebase style (no `try-with-resources` was idiomatic in academic Java until well after this naming convention — the `726` course code suffix dates the project). Without it, `Connection`/`Statement`/`ResultSet` leak on exception paths.
- **Recommendation:** Refactor every DAO method to `try (Connection c = ds.getConnection(); PreparedStatement ps = ...) { ... }`. Java 7+ has been standard for over a decade — safe to require.

### M5. Vietnamese/diacritic-heavy identifiers and a non-ASCII PDF filename
- **Signal:** `Phân tích thiết kế hệ thống.pdf` plus Vietnamese-shorthand class names (`HDTrucTiep`, `NVQL`, `HDMChitiet`).
- **Risk:** CI portability (Windows path encoding), Git on macOS/Linux NFC/NFD normalization issues, IDE indexing in mixed environments. Future maintainers without Vietnamese context will struggle.
- **Recommendation:** Keep domain terms but add a glossary in README; rename binary asset to ASCII or keep but ensure repo uses `core.precomposeunicode=true` on macOS.

### M6. No logging framework
- **Signal:** No `log4j*.properties`, `logback.xml`, or `slf4j` reference in the inventory.
- **Risk:** `System.out.println` / `e.printStackTrace()` is the default — no audit trail of failed logins, no DB error capture.
- **Recommendation:** Add SLF4J + Logback; log failed logins to a separate appender for basic intrusion detection.

---

## 🟢 LOW-Severity Findings

### L1. Numeric suffix `726` repeated on every class/JSP
- Likely a student ID / group identifier. Harmless but signals copy-paste templating. If the project is ever extracted from its academic context, rename to a meaningful prefix.

### L2. Mixed casing in package names
- `DAO726` and `Entity726` violate Java convention (`com.example.qlst.dao`, `com.example.qlst.entity`). Low impact but flagged by every modern linter.

### L3. View-fragment duplication
- `Header726.jsp` / `Footer726.jsp` / `Menu726.jsp` / `MenuQL726.jsp` suggests includes are used, which is good — but two menu files hint at copy-paste rather than role-conditional rendering. Consolidate to one menu that branches on `session.getAttribute("role")`.

### L4. Assets committed at full size
- Background `ptitnen.jpg` and `Toa_nha_A2_PTIT.jpg` likely contribute most of the 5.3 MB repo weight. Compress or move to a CDN/static dir.

### L5. No `.editorconfig` / formatter config
- Style drift across contributors; trivial fix.

---

## Maintainability Score (qualitative)
| Dimension | Rating | Note |
|---|---|---|
| Testability | ❌ Very Low | No tests, tight coupling JDBC↔JSP |
| Security posture | ❌ Very Low | SQLi/XSS/plaintext-creds shape all likely present |
| Build reproducibility | ⚠️ Low | Ant + NetBeans-specific paths |
| Layering | ⚠️ Medium | DAO/Entity separation exists; service layer absent |
| Documentation | ✅ Decent | PDF design doc + README present (rare for student projects) |
| Internationalization readiness | ⚠️ Mixed | UTF-8 not guaranteed in JSPs |

---

## Top 5 Actions, in Order
1. **Verify and fix SQL injection in `TKKH_DAO726` (login) first**, then sweep remaining DAOs.
2. **Hash passwords with BCrypt** and write a one-shot migration.
3. **Add a session/role `Filter`** registered in `web.xml` covering `GDQL*.jsp` and `MenuQL*.jsp`.
4. **Escape all JSP output** via JSTL `<c:out>` / `fn:escapeXml`.
5. **Introduce JUnit + H2** with at least 1 happy-path and 1 failure test per DAO; gate Ant `dist` target on `test`.

---

## What I Could Not Verify Without File Reads
- Actual SQL construction style (Statement vs PreparedStatement)
- Whether passwords are hashed
- Presence/absence of any `Filter` or `web.xml` security-constraint
- Whether `try-with-resources` is used
- Hardcoded credential locations

If you can grant read access to `F:\03_POC_PROJECTS\Supermarket-Management-System_JavaServerlet_JSP\`, I'll confirm each "needs verification" finding with exact file/line citations.
