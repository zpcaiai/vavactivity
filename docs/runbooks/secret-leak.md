# Secret leak

## Symptoms and impact

A credential appears in source, logs, artifacts, browser assets, screenshots, or an unauthorized store.

## Detect

Treat scanner or human reports as real until disproved; identify secret type, privileges, versions, exposure window, and access logs without repeating the value.

## Immediate containment

Disable/revoke the credential, suspend affected sessions/tokens, restrict the leak location, and open a security incident. Deleting Git history alone is not rotation.

## Recovery

Issue a least-privilege replacement through the approved secret provider, deploy, verify consumers, revoke every old version, and scan all build/log contexts.

## Verification and rollback

Prove the old credential fails and the new one works without disclosure. Roll back application code only with a safe compatible replacement secret.

## Communication and review

Use the security incident channel and required legal/privacy escalation. Review root cause, access, blast radius, and detection controls.
