# Service inventory

| Service | Authority | Health | Scaling |
|---|---|---|---|
| API | synchronous domain decisions and writes | live, startup, ready | horizontal, stateless |
| default worker | durable domain jobs | process/queue metrics | by queue delay |
| AI worker | AI, knowledge, recommendation work | queue/provider metrics | independently capped |
| notification worker | in-app/email delivery | queue/provider metrics | independently scalable |
| privacy worker | export, erasure, retention | queue/audit metrics | restricted concurrency |
| safety worker | block propagation and safety rules | queue/safety alerts | prioritized |
| media worker | object processing | queue/object metrics | resource-based |
| scheduler | enqueue schedules only | heartbeat | singleton |
| user web | public/member SPA | HTTP | immutable static replicas |
| admin web | operator SPA | HTTP | immutable static replicas |
| reverse proxy | TLS and routing | HTTP/TLS | redundant edge |

PostgreSQL is business truth; Redis is reconstructable coordination; object storage holds API-governed objects. External providers are never truth for local authorization or entitlement state.
