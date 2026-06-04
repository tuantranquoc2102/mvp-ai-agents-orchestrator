# Diagram

_Agent: `architect` (Software Architect)_  
_Status: `success` · attempts: 1_

---

```mermaid
flowchart TD
    Client[Client / Mobile App]
    Router[v4 Router<br/>chi.Router]
    Downtime[Downtime Middleware]
    LimitPayload[LimitPayload 5MB]
    AuthC[Auth Middleware<br/>authc.Middleware]
    BPDetails[bp.Details Middleware<br/>Fetch BP Context]
    BPCache[(BP Context Cache)]
    ChartsHandler[usage.Charts Handler<br/>GET /v4/charts/premises_id]
    ParseParams{Parse Query Params<br/>type, from, to, granularity}
    ValidateParams{Validate Params}
    ErrResp[Return 4xx Error]
    BPContext[Extract BP Context<br/>premises_id, account, meter]
    DispatchType{Chart Type?}
    AMICharts[ami.Charts Service<br/>AMI Usage Data]
    PPMSCharts[ppms.Charts Service<br/>Prepaid Meter Data]
    SMRDCharts[smrd Service<br/>Self Meter Reads]
    BilledCharts[usage.Billed<br/>Billed Consumption]
    PeerComp[usage.PeerComparison<br/>Peer Benchmark]
    AMIBackend[(AMI Backend API)]
    PPMSBackend[(PPMS Backend)]
    SMRDStore[(SMRD Store)]
    BillingBackend[(Billing Backend)]
    Aggregator[Aggregate and Normalize<br/>Time Series Data]
    Response[JSON Response<br/>Chart Series]

    Client -->|HTTP GET request| Router
    Router --> Downtime
    Downtime -->|service up| LimitPayload
    Downtime -->|down| ErrResp
    LimitPayload --> AuthC
    AuthC -->|token valid| BPDetails
    AuthC -->|unauthorized| ErrResp
    BPDetails -->|lookup| BPCache
    BPCache -->|hit or miss fetch| BPDetails
    BPDetails -->|context attached| ChartsHandler
    ChartsHandler --> ParseParams
    ParseParams --> ValidateParams
    ValidateParams -->|invalid| ErrResp
    ValidateParams -->|valid| BPContext
    BPContext --> DispatchType
    DispatchType -->|AMI meter| AMICharts
    DispatchType -->|prepaid| PPMSCharts
    DispatchType -->|self read| SMRDCharts
    DispatchType -->|billed view| BilledCharts
    DispatchType -->|peer view| PeerComp
    AMICharts --> AMIBackend
    PPMSCharts --> PPMSBackend
    SMRDCharts --> SMRDStore
    BilledCharts --> BillingBackend
    PeerComp --> BillingBackend
    AMIBackend --> Aggregator
    PPMSBackend --> Aggregator
    SMRDStore --> Aggregator
    BillingBackend --> Aggregator
    Aggregator --> Response
    Response --> Client
    ErrResp --> Client
```
