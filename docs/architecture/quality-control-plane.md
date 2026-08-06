# Batch 21 quality control plane

The quality module is an evidence registry and release decision system layered over VAV's business modules. It does not replace their tests or manufacture external certification.

## Data and decision flow

`quality-manifest.yaml` supplies versioned requirements, capabilities, flows and draft gate definitions. Deterministic source scanning inventories module contracts, routes, OpenAPI operations, migrations, permissions, events and tests. Verified links form the trace graph; missing critical links create owned gaps.

Evidence is accepted only when it identifies a release, Git commit and environment, carries integrity metadata, is current, and has an independent validator. Gate definitions are independently approved and use a closed declarative DSL. Evaluation records every input, observed value, evidence identifier and failure reason. Blocker failures and non-waivable failures always produce `NO_GO`. A valid Required-gate Waiver may produce `CONDITIONAL_GO`, but production certification accepts only `GO` and requires an independent certifier.

## Security boundaries

- No gate can execute Python, SQL, shell or network commands.
- Artifact references are encrypted and never returned in plaintext by list APIs.
- Requirement, gate, Waiver, evidence and certification approvals enforce separation of duties.
- Waivers have exact scope, mitigation, bounded expiry and revocation.
- All mutations emit `quality.*` administrator audit events.
- Missing and expired evidence fail closed.

## Evidence status

`scripts/quality/control.py release-report` proves local structural checks only. Its production status remains `NOT_CERTIFIED` and `release_allowed=false` until real penetration, recovery, UAT and production approval evidence is independently registered and accepted.
