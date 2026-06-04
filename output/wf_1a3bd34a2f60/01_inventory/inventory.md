# Inventory

_Agent: `researcher` (Research Specialist)_  
_Status: `success` · attempts: 1_

---

# Codebase Inventory Summary

## Project Overview
**Supermarket Management System** — a Java Servlet/JSP web application (legacy NetBeans Ant-based project, likely an academic assignment at PTIT given the imagery).

- **Path:** `F:\03_POC_PROJECTS\Supermarket-Management-System_JavaServerlet_JSP`
- **Total size:** ~5.3 MB across 50 files
- **Structure:** Single Ant-based web project rooted at `QLST_12/` (QLST = "Quản Lý Siêu Thị" / Supermarket Management, course code 12)

## Dominant Languages / File Types
| Type | Count | Role |
|---|---|---|
| Java | 19 | DAO + Entity layers |
| JSP | 13 | View / presentation layer |
| XML | 4 | Ant build + NetBeans project metadata |
| PNG/JPG | 6 | UI assets (logos, backgrounds) |
| Properties | 2 | NetBeans build configuration |
| CSS | 2 | Styling (login + global) |
| PDF | 1 | System analysis & design document (Vietnamese) |
| Markdown | 1 | README |
| MANIFEST.MF | 1 | WAR/JAR manifest |

**Notable absence:** No Servlet `.java` classes are visible in the file list — only DAO and Entity packages. Controller logic is likely embedded in JSP scriptlets (typical Model 1 architecture) or servlets are unlisted.

## Top-Level Notable Files
- `README.md` — project description
- `LICENSE` — license terms
- `Phân tích thiết kế hệ thống.pdf` — Vietnamese system analysis & design document

## Likely Entry Points
- **`QLST_12/web/Trangchu726.jsp`** — home page ("Trang chủ" = Home)
- **`QLST_12/web/GDDangNhap726.jsp`** — login screen ("Giao Diện Đăng Nhập")
- **`QLST_12/web/GDDangky726.jsp`** — registration screen
- **`QLST_12/web/GDQL726.jsp`** / `MenuQL726.jsp` — management console / admin menu

## Config & Build Files
| File | Purpose |
|---|---|
| `QLST_12/build.xml` | Primary Ant build entry point |
| `QLST_12/nbproject/build-impl.xml` | NetBeans-generated Ant implementation |
| `QLST_12/nbproject/ant-deploy.xml` | Deployment targets (likely to Tomcat/GlassFish) |
| `QLST_12/nbproject/project.xml` | NetBeans project descriptor |
| `QLST_12/nbproject/project.properties` | Build paths, classpath, target server |
| `QLST_12/nbproject/genfiles.properties` | Generated-file tracking |
| `QLST_12/src/conf/MANIFEST.MF` | WAR manifest |

## Architecture Snapshot
Classic 3-layer JSP/Servlet design:
- **Entity layer** (`src/java/Entity726/`): 13 POJOs — `KhachHang` (customer), `NVBH/NVGH/NVK/NVQL` (staff roles: sales/delivery/warehouse/manager), `MatHang` (product), `HoaDonMua/HDTrucTiep` (purchase/direct invoices), `NhaCungCap` (supplier), `SieuThi` (supermarket), `TKKH` (customer account).
- **DAO layer** (`src/java/DAO726/`): 6 data-access classes — base `DAO726`, plus `HDTT_DAO726`, `HoadonMua_DAO726`, `KH_DAO726`, `NVQL_DAO726`, `TKKH_DAO726`.
- **View layer** (`web/`): 13 JSPs with `GD*` (Giao Diện = "Interface/Screen") naming, shared `Header726.jsp`/`Footer726.jsp`/`Menu*` fragments.
