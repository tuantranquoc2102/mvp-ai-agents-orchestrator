# Diagram

_Agent: `architect` (Software Architect)_  
_Status: `success` · attempts: 1_

---

```mermaid
flowchart TD
    Client[Mobile or Web Client]
    M2M[M2M Service via OAuth2]
    Gateway[Gateway Router<br/>cmd/serverd/router]
    V4Router[v4 Router<br/>internal/app/v4/routes.go]
    Downtime[Downtime Middleware]
    LimitPayload[LimitPayload 5MB]
    AuthC[authc.Middleware<br/>Scope and IDToken]
    BasicIAM[basiciam RequireAccessToken<br/>and Audience M2M]
    ScopeChart[RequireClaimScope<br/>M2M Read Chart]
    BPDetailsJWT[bp.DetailsByJWTMiddleware<br/>extract IAM_ID from JWT]
    BPDetailsForm[bp.DetailsByFormMiddleware<br/>extract IAM_ID from form]
    BPLoad[bp Load<br/>fetch business partner details]
    BPCache[bp Cache<br/>cached BP context]
    BPCtx[bp.Context<br/>premises and accounts]
    ChartsHandler[usage.Charts Handler<br/>/v4/charts/premises_id]
    AMICharts[v3 ami.Charts<br/>aggregate readings]
    AMIDownload[v3 ami.Download<br/>fetch interval data]
    Stubs[stubs.Client<br/>upstream AMI service]
    NoncesDB[(request_nonces table<br/>idempotency store)]
    BPStore[(BP details store)]
    Response[Chart JSON Response]

    Client -->|HTTPS request| Gateway
    M2M -->|HTTPS with access token| Gateway
    Gateway --> V4Router
    V4Router --> Downtime
    Downtime --> LimitPayload

    LimitPayload -->|external authenticated| AuthC
    LimitPayload -->|internal M2M| BasicIAM

    AuthC --> BPDetailsJWT
    BasicIAM --> ScopeChart
    ScopeChart --> BPDetailsForm

    BPDetailsJWT -->|cache lookup| BPCache
    BPDetailsForm -->|cache lookup| BPCache
    BPCache -->|hit| BPCtx
    BPCache -->|miss| BPLoad
    BPLoad --> BPStore
    BPLoad --> BPCtx

    BPCtx -->|premises authorized| ChartsHandler
    BPCtx -->|premises not found| Deny{Authorization Check}
    Deny -->|fail| Err[403 or 404 Error]

    ChartsHandler -->|validate premises_id| ValPrem{Premises valid}
    ValPrem -->|no| Err
    ValPrem -->|yes| AMICharts

    ChartsHandler -->|idempotency nonce| NoncesDB
    AMICharts --> AMIDownload
    AMIDownload -->|RPC call| Stubs
    Stubs -->|raw readings| AMIDownload
    AMIDownload -->|interval series| AMICharts
    AMICharts -->|aggregated series| ChartsHandler
    ChartsHandler --> Response
    Response --> Client
    Response --> M2M
```
