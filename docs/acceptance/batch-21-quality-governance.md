# Batch 21 acceptance

Required technical gates:

```bash
make quality-verify
make acceptance
make skill-verify
```

Acceptance requires 21 separately registered project/Batch 1-20 requirements, 12 Batch 21 Skills, 21 backend module contracts, an 87-revision linear migration chain, exact quality RBAC, restricted gate operators, independent approvals, expiring evidence and Waivers, `NO_GO` for missing or blocker evidence, administrator route tests, and a generated release report.

Local PASS does not certify production. Penetration testing, a real restore drill, UAT and production approval remain `NOT_RUN`/`NOT_CERTIFIED` until their named evidence is supplied and validated.
