# Private photo processing and review

Decode, strip metadata, re-encode and thumbnail every upload before it can be reviewed. A
declared MIME type that disagrees with the decoded image is rejected. Quality checks are
non-identifying and advisory: no biometric template is derived and cross-site face search stays
off. Exactly one primary photo may be live, enforced by a partial unique index plus a profile-row
lock. Access uses short-lived viewer-bound tokens; storage object keys never leave the backend,
and deleting or rejecting a photo revokes outstanding tokens immediately.
