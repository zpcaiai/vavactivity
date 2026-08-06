# Saga architecture

Saga definitions and progress are durable in PostgreSQL. Each side-effecting step has a stable idempotency key and request hash. Registered domain commands return typed receipts; inbox event versions reject old events and buffer future events. Worker recovery resumes persisted steps and never treats an optional notification failure as reversal of a successful business fact.
