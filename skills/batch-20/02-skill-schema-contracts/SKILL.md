---
name: vav-skill-schema-contracts
description: Implement or review VAV Skill input, output, error, configuration, sensitive-field, code-generation, fixture, or schema-compatibility contracts.
---

Use JSON Schema 2020-12 as source of truth. Require object roots and `additionalProperties: false`; annotate sensitive fields and redact logs. Treat removed fields, new required fields, narrowed enums, type changes, and classification changes as breaking. Run schema generation/diff and `make skill-schema-test`.
