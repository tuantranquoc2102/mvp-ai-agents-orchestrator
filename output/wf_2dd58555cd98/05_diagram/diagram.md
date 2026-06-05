# Diagram

_Agent: `architect` (Software Architect)_  
_Status: `success` · attempts: 1_

---

```mermaid
flowchart TD
    Req[/HTTP GET ubm trail monthly<br/>params accountNo fromDate toDate/] --> Auth{SkalboxM2MSecured<br/>scope read spd skalbox trails valid?}
    Auth -->|invalid token or scope| Resp401[/401 Unauthorized/]
    Auth -->|valid| Ctrl[TrailController.getMonthlyTrails]
    Ctrl --> CallChart[chartService.getMonthly<br/>accountNo fromDate toDate]
    CallChart --> AcctLookup[accountService.findAccount accountNo]
    AcctLookup --> AcctDB[(External: Accounts DB)]
    AcctDB --> AcctFound{account exists?}
    AcctFound -->|no| Resp404[/404 Account Not Found/]
    AcctFound -->|yes| AcctType{premise type?}
    AcctType -->|MDH meter| MDHCall[MDH API<br/>retrieve scalar meter info]
    AcctType -->|BDL billing| BDLCall[BDL Billing API]
    MDHCall --> SMRDCall[SMRDService.getMeterReadings]
    SMRDCall --> SMRDBackend[SMRD Backend API]
    SMRDBackend --> BuildMDH[Build MDHChart series]
    BDLCall --> BuildBDL[Build BDLChart series]
    BuildMDH --> ChartOk{chart data returned?}
    BuildBDL --> ChartOk
    ChartOk -->|empty or error| ThrowEx[throw ChartApiException]
    ThrowEx --> Resp5xx[/5xx Chart API Error/]
    ChartOk -->|ok| FormatCheck{request path<br/>monthly or monthly csv?}
    FormatCheck -->|monthly JSON| Resp200Json[/200 JSON MDHChart or BDLChart/]
    FormatCheck -->|monthly csv| FormatCsv[Map rows with CSV_MONTHLY template]
    FormatCsv --> Resp200Csv[/200 text csv stream<br/>Flux ResponseCsv/]
```
