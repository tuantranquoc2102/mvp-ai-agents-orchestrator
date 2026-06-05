# Diagram

_Agent: `architect` (Software Architect)_  
_Status: `success` · attempts: 1_

---

```mermaid
flowchart TD
    Request[/GET /admin/customer<br/>bpNo, userId/] --> Controller[AdminController.getCustomer]
    Controller --> LogStart[Log: getCustomerDetails Start]
    LogStart --> ServiceCall[adminService.getCustomer<br/>bpNo, userId]
    ServiceCall --> SAPInterface[SAP service layer]
    SAPInterface --> CustomerTypeCheck{Customer type?}
    CustomerTypeCheck -->|EBS customer| EBSCall[SAP API<br/>/CustomerDetailsRetrieval]
    CustomerTypeCheck -->|MSSL customer| MSSLCall[SAP API<br/>/MSSLCustomerDetailsRetrieval]
    CustomerTypeCheck -->|Profile lookup| ProfileCall[SAP API<br/>/CustomerProfileRetrieval]
    EBSCall --> SAPResponseCheck{SAP response status?}
    MSSLCall --> SAPResponseCheck
    ProfileCall --> SAPResponseCheck
    SAPResponseCheck -->|success| MaskFields[Apply MaskingUtil<br/>to sensitive fields]
    SAPResponseCheck -->|error code returned| ErrorBranch{Error type?}
    MaskFields --> SubscriptionCheck{Has subscription data?}
    SubscriptionCheck -->|YesOrNo = Y| IncludeSubscription[Attach Subscription details]
    SubscriptionCheck -->|YesOrNo = N| SkipSubscription[Skip subscription]
    IncludeSubscription --> BillPrefCheck{Bill preference flag?}
    SkipSubscription --> BillPrefCheck
    BillPrefCheck -->|OnOrNo = ON| IncludeBillPref[Include bill preference]
    BillPrefCheck -->|OnOrNo = OFF| SkipBillPref[Omit bill preference]
    IncludeBillPref --> BuildResponse[Build GetCustomerResponse DTO]
    SkipBillPref --> BuildResponse
    BuildResponse --> Resp200[/200 OK<br/>GetCustomerResponse JSON/]
    ErrorBranch -->|customer not found| Resp404[/4xx Not Found<br/>error response/]
    ErrorBranch -->|SAP backend failure| Resp500[/5xx SAP Error<br/>ERROR_RES/]
    ErrorBranch -->|invalid bpNo or userId| Resp400[/4xx Bad Request/]
```
