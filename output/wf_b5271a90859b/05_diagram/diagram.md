# Diagram

_Agent: `architect` (Software Architect)_  
_Status: `success` · attempts: 1_

---

```mermaid
flowchart TD
    Req[/HTTP GET /admin/customer<br/>query: bpNo, userId/] --> Aspect[LoggableAspect<br/>intercepts @Loggable]
    Aspect --> ReqLog[RequestLoggingDecorator<br/>logs inbound request]
    ReqLog --> Ctrl[AdminController.getCustomer<br/>bpNo, userId]
    Ctrl --> LogStart[log.info<br/>AdminController :: getCustomerDetails :: Start]
    LogStart --> Svc[AdminServiceImpl.getCustomer<br/>bpNo, userId]

    Svc --> ValBp{bpNo present<br/>and valid?}
    ValBp -->|no| Err400[/400 BadRequest<br/>GetCustomerResponse error/]
    ValBp -->|yes| ValUser{userId present?}
    ValUser -->|no| Err400

    ValUser -->|yes| FetchSap[SAP service<br/>fetch customer by bpNo]
    FetchSap --> SapApi[SAP Backend API]
    SapApi --> SapResult{SAP returned<br/>customer?}
    SapResult -->|not found| Err404[/404 NotFound<br/>customer not found/]
    SapResult -->|error| Err5xx[/5xx error response<br/>via onErrorResume/]

    SapResult -->|found| FetchProfile[ProfileApi connector<br/>fetch profile by userId]
    FetchProfile --> ProfApi[Profile API]
    ProfApi --> ProfBranch{Profile<br/>retrieved?}
    ProfBranch -->|no| PartialProfile[set profile fields null<br/>continue aggregation]
    ProfBranch -->|yes| MergeProfile[merge profile<br/>into response]

    PartialProfile --> Banners
    MergeProfile --> Banners[NotificationBannersServiceImpl<br/>load active banners for bpNo]
    Banners --> BannerStore[(External: Banners datastore)]
    BannerStore --> Holidays[HolidaysServiceImpl<br/>fetch holiday calendar]
    Holidays --> HolidayStore[(External: Holidays datastore)]
    HolidayStore --> Mods[ModificationServiceImpl<br/>fetch pending modifications]
    Mods --> ModStore[(External: Modifications store)]

    ModStore --> Perm{Caller has<br/>READ_CUSTOMER permission?}
    Perm -->|no| Err403[/403 Forbidden<br/>insufficient permission/]
    Perm -->|yes| Aggregate[Build GetCustomerResponse<br/>customer + profile + banners + holidays + modifications]

    Aggregate --> RespLog[ResponseLoggingDecorator<br/>logs outbound response]
    RespLog --> Resp200[/200 OK<br/>GetCustomerResponse JSON/]

    Err400 --> RespLog
    Err403 --> RespLog
    Err404 --> RespLog
    Err5xx --> RespLog
```
