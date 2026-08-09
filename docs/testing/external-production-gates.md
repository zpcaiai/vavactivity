# External production gate test cases

These cases produce executable local evidence without converting local results into production certification. A production gate accepts only artifacts from the named production or independent environment, bound to the deployed commit and artifact digest.

| Gate | Executable cases | Local result meaning | Production completion condition |
| --- | --- | --- | --- |
| Browser UAT | Desktop Chrome: language entry, catalog, admin login; nonblank content; key controls; navigation; console/page errors; HTTP 5xx; overlays; axe; screenshots and traces | `LOCAL_PASS` | Named UAT users execute against the deployed artifact in approved browsers |
| Device UAT | Pixel 7 Chrome touch/mobile emulation; viewport overflow; same page and accessibility assertions | `LOCAL_PASS`; physical device remains `NOT_EVALUATED` | Approved real iOS/Android devices and OS/browser matrix |
| Load | Baseline and steady public journey with p95/p99, failure-rate, and check thresholds | `LOCAL_PASS` | Production-like topology/data and approved load profile |
| Spike | Abrupt VU increase and recovery | `LOCAL_PASS` | Production-like autoscaling and dependency quotas observed |
| Stress | Progressive load above expected peak | `LOCAL_PASS` | Capacity limit, degradation mode, and recovery documented |
| Soak | Configurable sustained workload; local profile is one minute, certification profile defaults to two hours | `LOCAL_PASS` | Approved long soak with resource-leak and saturation telemetry |
| DAST | Security headers, hostile CORS, TRACE rejection, traversal and error-leak checks | `LOCAL_PASS` | Authenticated production-safe DAST by approved scanner |
| API fuzz | Deterministic malformed queries and bodies across protected and public-read OpenAPI operations | `LOCAL_PASS` | Full approved fuzz campaign with rate/safety controls |
| Penetration regression | Malformed JWT and spoofed admin header bypass attempts | `LOCAL_PASS`; independent test `NOT_EVALUATED` | Independent scoped penetration test and remediation closure |
| Backup/restore | Encrypted backup integrity and isolated Postgres/object restore | `LOCAL_PASS` | Production backup selected and restored in approved isolated environment |
| Chaos | API, Redis, worker, MinIO and scheduler stop/restart with recovery verification | `LOCAL_PASS` | Production-safe fault injection with SLO and customer-impact guardrails |
| HA | API singleton is stopped and its outage is confirmed before recovery | `FAIL_SINGLE_INSTANCE_OUTAGE_CONFIRMED`; production HA remains `NOT_EVALUATED` | Load-balancer, replica, database failover and dependency failover evidence |
| DR | Isolated local restore only | `NOT_EVALUATED` for regional DR/RPO/RTO | Regional failover and measured production RPO/RTO exercise |
| 24h/7d/30d observation | Append-only endpoint samples; start-anchor, cadence, latest-sample, clean-worktree and single-commit checks | `IN_PROGRESS` until wall-clock duration elapses | Production endpoints, deployed commit/artifact identity, required cadence, and every sample passing |

Commands:

```bash
make external-browser-uat
make external-performance-local
make external-security-local
make external-resilience-local
make external-observation-sample
```
