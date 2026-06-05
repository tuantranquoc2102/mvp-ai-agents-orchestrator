# Diagram

_Agent: `architect` (Software Architect)_  
_Status: `success` · attempts: 1_

---

```mermaid
flowchart TD
    User[Admin or Customer User]
    Browser[Web Client]
    CORS[CorsConfig and CorsProperties]
    SecFilter[SecurityConfiguration and Auth0 JWT]
    PermFilter[PermissionFilter]
    ReqLog[RequestLoggingFilter and Decorators]
    Aspect[LoggableAspect and LogMasking]

    AdminCtrl[AdminController /admin]
    ApprovalCtrl[ApprovalController /approvals]

    AdminSvc[AdminServiceImpl]
    UserSvc[UserServiceImpl]
    AuditSvc[AuditServiceImpl]
    NotifSvc[NotificationBannersServiceImpl]
    HolidaySvc[HolidaysServiceImpl]
    SapSvc[SAPServiceImpl]

    WebClient[WebClientConfiguration]
    Yggdrasil[Yggdrasil Customer API]
    SAPBackend[SAP Backend]
    Auth0[Auth0 Identity Provider]
    AuditStore[Audit Log Store]
    NotifStore[Notifications Store]

    User --> Browser
    Browser -->|HTTP request with JWT| CORS
    CORS --> SecFilter
    SecFilter -->|verify token via Auth0| Auth0
    SecFilter --> PermFilter
    PermFilter -->|check Permission enum and SkipURLPermission| PermDecision{Authorized}
    PermDecision -->|no| Reject[401 or 403 Response]
    PermDecision -->|yes| ReqLog
    ReqLog --> Aspect

    Aspect -->|route /admin/customers| AdminCtrl
    Aspect -->|route /approvals| ApprovalCtrl

    AdminCtrl -->|getCustomers search by type and string| AdminSvc
    AdminCtrl -->|updateBpNo and subscription ops| AdminSvc
    AdminCtrl -->|forgotPassword| UserSvc
    ApprovalCtrl -->|approve or reject customer changes| AdminSvc

    AdminSvc -->|reactive WebClient call| WebClient
    UserSvc --> WebClient
    NotifSvc --> WebClient
    HolidaySvc --> WebClient
    SapSvc --> WebClient

    WebClient -->|SearchCustomers and GetCustomerResponse| Yggdrasil
    WebClient -->|purchase order and account data| SAPBackend
    UserSvc -->|forgot password and user mgmt| Auth0

    AdminSvc -->|emit AuditType event| AuditSvc
    UserSvc -->|emit AuditType event| AuditSvc
    ApprovalCtrl -->|emit AuditType event| AuditSvc
    AuditSvc -->|persist Audit DTO| AuditStore

    NotifSvc -->|fetch banners| NotifStore
    AdminCtrl -->|response BaseResponse| Browser
    ApprovalCtrl -->|response BaseResponse| Browser

    classDef store fill:#f4e1c1,stroke:#a06a00
    classDef external fill:#d6e9ff,stroke:#0050a0
    classDef security fill:#ffd6d6,stroke:#a00000
    class AuditStore,NotifStore store
    class Yggdrasil,SAPBackend,Auth0 external
    class SecFilter,PermFilter,CORS security
```
