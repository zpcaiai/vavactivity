# RPO and RTO objectives

| Asset | Initial RPO | Initial RTO | Validation |
|---|---:|---:|---|
| PostgreSQL core data | 15 minutes | 4 hours | PITR plus full restore/invariants |
| Object storage | 24 hours | 8 hours | inventory and protected-object sampling |
| Config/manifests | 24 hours | 4 hours | checksum and release compatibility |
| Redis | reconstructable | 1 hour | cache rebuild/outbox replay |
| Static web artifacts | zero from signed artifact | 1 hour | digest verification and smoke |

These are proposed objectives pending business and infrastructure-owner approval. Security, privacy, safety, and financial records require the strictest integrity checks even if this extends restoration time; recovery must not bypass controls to meet an SLO.
