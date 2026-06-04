# Diagram

_Agent: `architect` (Software Architect)_  
_Status: `success` · attempts: 1_

---

```mermaid
flowchart TD
    Client[Mobile or Web Client]
    M2M[M2M Service Caller]

    subgraph Router["v4 Router - chi"]
        ExtGroup[external group]
        IntGroup[internal group]
    end

    subgraph CommonMW["Common Middlewares"]
        Downtime[downtime.Middleware]
        Limit[LimitPayload 5MB]
    end

    subgraph AuthExt["External Auth Chain"]
        AuthC[authc.Middleware<br/>Scope + IDToken]
        BPjwt[bp.DetailsByJWTMiddleware]
    end

    subgraph AuthInt["Internal M2M Auth Chain"]
        AccessTok[basiciam.RequireAccessToken<br/>auth0.JWKSKeyFunc]
        Audience[basiciam.RequireClaimAudience<br/>AudM2M]
        Scope[basiciam.RequireClaimScope<br/>ScopeM2MReadChart]
        BPform[bp.DetailsByFormMiddleware]
    end

    Route1{{GET /v4/charts/premises_id<br/>authenticated}}
    Route2{{GET /v4/user/charts/premises_id<br/>M2M internal}}

    Handler[handler.Wrap usage.Charts]

    subgraph BPCtx["BP Context Resolution"]
        BPCache[bp.Cache lookup]
        BPSvc[BP details service]
        BPInject[Inject BP details<br/>into request context]
    end

    subgraph ChartLogic["usage.Charts Handler Logic"]
        ParsePremises[Parse premises_id<br/>and query params]
        ValidateAcct[Validate premises belongs<br/>to authenticated account]
        FetchAMI[Fetch AMI consumption<br/>via v3 ami.Charts]
        FetchBilled[Fetch billed usage data]
        FetchPeer[Compute peer comparison]
        Aggregate[Aggregate chart series]
    end

    AMIBackend[(AMI Backend Service)]
    BillingBackend[(Billing Backend)]
    PeerStore[(Peer Comparison Store)]
    BPStore[(BP Details Source)]

    Response[/JSON Chart Response/]
    AuthErr[/401 or 403 Error/]
    NotFound[/404 Premises Not Found/]

    Client --> ExtGroup
    M2M --> IntGroup

    ExtGroup --> Downtime --> Limit --> AuthC --> BPjwt --> Route1
    IntGroup --> AccessTok --> Audience --> Scope --> BPform --> Route2

    AuthC -->|invalid token| AuthErr
    AccessTok -->|invalid token| AuthErr
    Scope -->|missing scope| AuthErr

    BPjwt --> BPCache
    BPform --> BPCache
    BPCache -->|miss| BPSvc
    BPSvc --> BPStore
    BPStore --> BPInject
    BPCache -->|hit| BPInject

    Route1 --> Handler
    Route2 --> Handler
    BPInject --> Handler

    Handler --> ParsePremises --> ValidateAcct
    ValidateAcct -->|mismatch| NotFound
    ValidateAcct -->|ok| FetchAMI
    FetchAMI --> AMIBackend
    FetchAMI --> FetchBilled
    FetchBilled --> BillingBackend
    FetchBilled --> FetchPeer
    FetchPeer --> PeerStore
    FetchPeer --> Aggregate
    Aggregate --> Response
```
