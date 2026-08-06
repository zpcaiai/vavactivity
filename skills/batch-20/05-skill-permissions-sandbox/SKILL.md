---
name: vav-skill-permissions-sandbox
description: Implement Skill permissions, caller/install/runtime authority intersections, confirmations, sandbox limits, network egress, SSRF controls, files, or Secret Broker access.
---

Effective authority is the intersection of caller, installation, manifest, and runtime policy. Deny dynamic escalation. Block localhost, private/link-local/metadata destinations, Docker sockets, host files, direct databases, and permanent plaintext secrets. Audit decisions and run `make skill-security-test`.
