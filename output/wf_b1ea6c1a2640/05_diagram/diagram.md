# Diagram

_Agent: `architect` (Software Architect)_  
_Status: `success` · attempts: 1_

---

```mermaid
flowchart TD
    Client[Client / Mobile App]
    M2M[M2M Service<br/>OAuth2 client]

    subgraph Edge[Chi Router v4]
        Downtime[downtime.Middleware]
        Payload[LimitPayload 5MB]
        AuthcMW[authc.Middleware<br/>Scope and IDToken]
        IAMToken[basiciam.RequireAccessToken<br/>auth0.JWKSKeyFunc]
        IAMAud[basiciam.RequireClaimAudience<br/>AudM2M]
        IAMScope[basiciam.RequireClaimScope<br/>ScopeM2MReadChart]
        BPJWT[bp.DetailsByJWTMiddleware]
        BPForm[bp.DetailsByFormMiddleware]
    end

    RouteExt[GET /v4/charts/premises_id<br/>external authenticated]
    RouteInt[GET /v4/user/charts/premises_id<br/>internal M2M]

    HandlerWrap[handler.Wrap]
    Charts[usage.Charts handler]

    ParseReq[Parse premises_id<br/>and query params]
    LoadBP[Load BP context<br/>IAM_ID and accounts]

    BPCache[(BP Cache<br/>v3/bp/cache.go)]
    AccountSvc[Account Service<br/>v4/account/all]

    Authorize{Premises belongs<br/>to BP?}
    Reject[401 / 403<br/>error response]

    AMICharts[v3/ami/charts<br/>chart aggregation]
    AMIDownload[v3/ami/download<br/>usage data fetch]
    PeerCmp[usage/peercomparison]
    Billed[usage/billed]

    AMIStore[(AMI Data Store<br/>upstream service)]
    BillStore[(Billing Store)]

    Aggregate[Build chart payload<br/>usage, billed, peers]
    Respond[JSON response]

    Client -->|Bearer JWT| Downtime
    M2M -->|OAuth2 access token| IAMToken

    Downtime --> Payload --> AuthcMW --> BPJWT --> RouteExt
    IAMToken --> IAMAud --> BPForm --> IAMScope --> RouteInt

    RouteExt --> HandlerWrap
    RouteInt --> HandlerWrap
    HandlerWrap --> Charts

    Charts --> ParseReq --> LoadBP
    LoadBP -->|cache lookup| BPCache
    LoadBP -->|miss| AccountSvc
    AccountSvc -->|populate| BPCache

    LoadBP --> Authorize
    Authorize -->|no| Reject
    Authorize -->|yes| AMICharts

    AMICharts --> AMIDownload
    AMICharts --> PeerCmp
    AMICharts --> Billed

    AMIDownload -->|fetch interval data| AMIStore
    PeerCmp -->|fetch neighbour stats| AMIStore
    Billed -->|fetch invoices| BillStore

    AMICharts --> Aggregate --> Respond
    Respond --> Client
    Respond --> M2M
```
