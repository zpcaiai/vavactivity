# Object storage unavailable

## Symptoms and impact

Uploads, protected downloads, media processing, privacy exports, and object backup fail; unrelated database workflows continue.

## Detect

Check object health, signed-request errors, worker dead letters, bucket policies, and provider status.

## Immediate containment

Deny private-object access on uncertainty, pause media/export jobs, retain database intents, and never publish an unscanned upload.

## Recovery

Restore endpoint/DNS/credentials, verify bucket/versioning/encryption policies, reconcile pending intents, and replay idempotent jobs.

For profile media, the private bucket must meet all of these conditions before
uploads are re-enabled:

- anonymous access is disabled and the browser endpoint is HTTPS outside local development;
- CORS allows `POST` and `GET` only from the configured user/admin origins, with no wildcard credentials;
- POST policies reject a wrong `Content-Type` and a body above the signed `content-length-range`;
- bucket versioning is disabled while browser-writable staging and immutable
  final objects share one bucket. A reusable staging policy on a versioned key
  can otherwise create unbounded retained versions without another API call;
- lifecycle cleanup covers abandoned `profile-media/uploads/` objects after the longest upload/finalize window;
- the `profile-media/assets/` prefix is not writable by browser upload policies;
- the `vav.profile_media.maintain_storage` task is routed to a running worker and its durable deletion queue has no stale `failed` rows.

The worker identity must retain `GetBucketVersioning`, `ListBucketVersions`,
`DeleteObject`, and `DeleteObjectVersion`. The application deletes all versions
and delete markers for historical/versioned keys; omitting any of those IAM
actions turns every privacy deletion into a retried 503 rather than silently
claiming the bytes were erased.

## Verification and rollback

Sample public/private access with two-user isolation, verify checksums and malware state, run export download checks, and revert the provider change if isolation fails. Exercise one valid presigned POST, one wrong-MIME POST, one oversized POST, and one browser CORS preflight against the actual provider; decoding a policy document is not storage enforcement evidence.

## Communication and review

Name affected object classes without exposing keys. Review retention, replication, permissions, and provider SLA.
