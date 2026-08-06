# Restore procedure

1. Declare an incident, freeze conflicting writes, choose an approved recovery point, and record release/schema/object identities.
2. Create an isolated network and fresh target services. Never restore over the only source copy.
3. Verify manifest checksums and authenticated encryption before decrypting into restricted temporary storage.
4. Restore PostgreSQL without owner/privilege inheritance; restore object archives with path traversal checks.
5. Verify Alembic revision, table inventory, business invariants, object inventory, encryption access, and release compatibility.
6. Inject new environment secrets, deploy the matching immutable release, run smoke, privacy, payment, safety, and complete E2E gates.
7. Obtain incident commander and data-owner approval before traffic. Monitor reconciliation and delayed jobs.
8. Securely remove temporary plaintext, preserve the drill report, and complete the post-incident review.

Local drill: `make backup backup-verify restore-drill restore-smoke`. It creates and destroys an isolated PostgreSQL container; it does not certify a managed-cloud PITR restore.
