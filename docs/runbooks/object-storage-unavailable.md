# Object storage unavailable

## Symptoms and impact

Uploads, protected downloads, media processing, privacy exports, and object backup fail; unrelated database workflows continue.

## Detect

Check object health, signed-request errors, worker dead letters, bucket policies, and provider status.

## Immediate containment

Deny private-object access on uncertainty, pause media/export jobs, retain database intents, and never publish an unscanned upload.

## Recovery

Restore endpoint/DNS/credentials, verify bucket/versioning/encryption policies, reconcile pending intents, and replay idempotent jobs.

## Verification and rollback

Sample public/private access with two-user isolation, verify checksums and malware state, run export download checks, and revert the provider change if isolation fails.

## Communication and review

Name affected object classes without exposing keys. Review retention, replication, permissions, and provider SLA.
