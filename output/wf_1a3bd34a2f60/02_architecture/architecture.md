# Architecture

_Agent: `architect` (Software Architect)_  
_Status: `success` · attempts: 1_

---

I cannot read the source files directly (permission denied), so I will base the architectural inference on the file structure, naming conventions, and the inventory metadata already provided.

---

# Architectural Analysis — Supermarket-Management-System (QLST_12)

## 1. Architectural Style

**Inferred style:** Classic JSP/Servlet **Model 1 / "thin 3-tier"** legacy Java EE web application — packaged as a WAR via NetBeans + Ant.

```
┌─────────────────────────────────────────────────────────────┐
│                     PRESENTATION (web/)                      │
│  GD*.jsp  (screens)   ─┐                                     │
│  Header/Footer/Menu   ─┼─► JSP scriptlets directly invoking  │
│  Trangchu, Dangxuat   ─┘    DAO classes (Model 1 pattern)    │
└──────────────────────────┬──────────────────────────────────┘
                           │ (no Servlet/Controller layer found)
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                     DATA ACCESS (DAO726)                     │
│  DAO726 (base)  ◄── HDTT_DAO726, HoadonMua_DAO726,           │
│                     KH_DAO726, NVQL_DAO726, TKKH_DAO726      │
└──────────────────────────┬──────────────────────────────────┘
                           │ JDBC (likely SQL Server / MySQL)
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                     DOMAIN (Entity726)                       │
│  13 anemic POJOs: KhachHang, NVBH/NVGH/NVK/NVQL, MatHang,   │
│  HoaDonMua, HDTrucTiep, NhaCungCap, SieuThi, TKKH, ...      │
└─────────────────────────────────────────────────────────────┘
                           ▲
                           │ External RDBMS (off-process)
```

## 2. Layers & Modules

| Layer | Package / Folder | Files | Responsibility |
|---|---|---|---|
| **View** | `QLST_12/web/*.jsp` | 13 JSPs | Rendering + (likely) request handling via scriptlets |
| **View fragments** | `Header726.jsp`, `Footer726.jsp`, `Menu726.jsp`, `MenuQL726.jsp` | 4 | Reusable layout includes |
| **Static assets** | `web/css/`, `web/image/` | 4 + images | Styling, branding (PTIT) |
| **Data Access** | `src/java/DAO726/` | 6 | JDBC CRUD per aggregate |
| **Domain (anemic)** | `src/java/Entity726/` | 13 | Plain getter/setter POJOs |
| **Build / config** | `nbproject/`, `build.xml`, `MANIFEST.MF` | 7 | Ant build, NetBeans descriptors |

**No** `Controller`, `Servlet`, `Service`, `Filter`, or `web.xml` is visible in the scan — strongly suggests Model 1 (JSP-direct) rather than Model 2 (MVC via Servlets). Worth double-checking: a `web.xml` may live under `web/WEB-INF/` which wasn't expanded in the inventory.

## 3. External Dependencies (inferred)

| Dependency | Evidence | Confidence |
|---|---|---|
| **Servlet container** (Tomcat / GlassFish) | `ant-deploy.xml`, WAR packaging, JSP | High |
| **JDBC driver** + RDBMS | DAO classes named after database tables; no ORM artefacts | High |
| **JSTL / JSP runtime** | JSP files | High |
| **No DI container** (no Spring, CDI) | No `applicationContext.xml`, no `beans.xml`, no annotations folder | High |
| **No ORM** (no Hibernate/JPA) | No `persistence.xml`, no `*Repository` interfaces | High |
| **No build/test framework beyond Ant** | No `pom.xml`, no `build.gradle`, no JUnit classes | High |

Communication is purely **synchronous, in-process method calls** between JSP → DAO → JDBC → DB. No messaging, no remote APIs, no caching tier.

## 4. Communication Patterns

- **JSP → DAO:** direct instantiation in scriptlets (`<% new KH_DAO726()... %>`) — typical Model 1 anti-pattern.
- **DAO → DB:** JDBC `Connection`/`PreparedStatement`, likely centralized in the base `DAO726` class.
- **Inter-JSP:** `<%@ include %>` / `jsp:include` for Header/Footer/Menu composition.
- **Auth/session:** likely `HttpSession` attribute checks scattered in JSPs (no Filter visible).

## 5. Structural Smells & Risks

| # | Smell | Evidence | Severity |
|---|---|---|---|
| 1 | **Missing Controller layer (Model 1)** | Zero servlet classes; only DAO + Entity. Business logic almost certainly lives in JSP scriptlets. | **High** — untestable, mixes concerns |
| 2 | **Anemic domain model** | 13 entities in `Entity726` with no behavior package alongside them. All logic ends up in DAOs or JSPs. | **High** |
| 3 | **Potential "God DAO" base class** | A single `DAO726.java` paired with 5 specialized DAOs — likely holds shared connection/`Statement` plumbing **and** generic CRUD. Risk of becoming a god module as features accrete. | **Medium** |
| 4 | **No Service / Use-Case layer** | DAOs are called directly from views. Cross-aggregate transactions (e.g., "create invoice + decrement stock") have nowhere to live atomically. | **High** |
| 5 | **DAO ↔ Entity coupling, but uneven coverage** | 13 entities vs only 6 DAOs. Entities `MatHang726`, `NhaCungCap726`, `SieuThi726`, `NVBH_726`, `NVGH_726`, `NVK_726` have **no corresponding DAO** — either dead code, or persistence logic is duplicated inside other DAOs / JSPs. | **Medium** |
| 6 | **Numeric suffix `726` everywhere** | Naming carries an external identifier (likely student/group ID) into class names. Hurts readability and makes renaming painful. | **Low** (cosmetic but pervasive) |
| 7 | **Mixed Vietnamese/English identifiers** | `KhachHang_726`, `HoaDonMua726`, `NVQL_DAO726`. Acceptable for academic project; problematic for any international maintenance. | **Low** |
| 8 | **No package structure under domain** | `Entity726` lumps customers, staff (4 role classes!), invoices, products, suppliers into one flat package. Likely violates aggregate boundaries. | **Medium** |
| 9 | **Four parallel staff entity classes (`NVBH/NVGH/NVK/NVQL_726`)** | Suggests inheritance was avoided — likely duplicated fields (id, name, phone…). Classic missing-abstraction smell. | **Medium** |
| 10 | **Cyclic risk: not yet observed but latent** | Flat packages + DAOs holding references back to multiple entities and likely to each other (e.g., invoice DAO needing customer DAO) — high probability of `DAO726 ↔ specific DAO` bidirectional dependency. **Cannot confirm without reading source.** | **Medium (latent)** |
| 11 | **Build system EOL** | NetBeans-Ant, no dependency manager (Maven/Gradle). Updates, CVE scanning, and CI integration are painful. | **Medium** |
| 12 | **No tests** | Zero `test/` folder, no JUnit. | **High** (for any future change) |
| 13 | **Static assets path leak** | `web/image/Toa_nha_A2_PTIT.jpg`, `ptit-logo.png` — institutional branding hard-coded into the deliverable. | **Low** |

## 6. Items That Need Verification (would require reading source)

To confirm or refute the above, inspect:
- `web/WEB-INF/web.xml` (if present) — would reveal any servlet mappings or filters that the file-count missed.
- `DAO726/DAO726.java` — confirm whether it is a god class (connection mgmt + generic queries + utility methods).
- Any JSP (e.g. `GDQL726.jsp`) — confirm scriptlets directly call DAOs.
- `nbproject/project.properties` — confirm target server, classpath JARs (JDBC driver, JSTL).

## 7. Summary Verdict

A **textbook legacy Model 1 JSP application**: tight coupling between view and persistence, no service layer, anemic flat-package domain with duplicated staff classes, and a probable god base-DAO. No cyclic packages can be proven from the file list alone, but the flat `Entity726` / `DAO726` packages combined with the missing service layer make cycles between DAOs the most likely structural failure mode if the source were inspected. Modernization (Spring Boot + JPA + proper MVC + Maven/Gradle + tests) would be a near-total rewrite rather than a refactor.
