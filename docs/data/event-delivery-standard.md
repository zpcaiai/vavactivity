# Event delivery standard

Domain changes enqueue canonical envelopes in the same PostgreSQL transaction. The Worker bridges pending events using `FOR UPDATE SKIP LOCKED`; consumers persist Inbox IDs and aggregate versions. Duplicates are harmless, future versions are buffered, gaps are visible, and replay must respect external side-effect idempotency.
