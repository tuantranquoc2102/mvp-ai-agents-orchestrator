# Diagram

_Agent: `architect` (Software Architect)_  
_Status: `success` · attempts: 1_

---

```mermaid
flowchart TD
    Request[/GET /admin/customer<br/>bpNo, userId query params/] --> Controller[AdminController.getCustomer]
    Controller --> LogStart[log.info AdminController getCustomerDetails Start]
    LogStart --> ServiceCall[adminService.getCustomer<br/>bpNo, userId]
    ServiceCall --> SAPCall[SAP API<br/>CUSTOMER_PROFILE_RETRIEVAL]
    SAPCall --> SAPResult{SAP call result?}
    SAPResult -->|success| BuildResp[Build GetCustomerResponse<br/>from SAP payload]
    SAPResult -->|error or empty| ErrorPath[Propagate error<br/>via Mono.error]
    BuildResp --> Resp200[/200 OK<br/>Mono GetCustomerResponse/]
    ErrorPath --> Resp5xx[/4xx or 5xx<br/>error response/]
```
