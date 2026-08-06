# Backup policy

PostgreSQL, object storage, and release/configuration metadata are backed up as one identified set. The scripts create a custom-format database dump, deterministic object archive, and configuration archive; each is streamed through AES-256-GCM encryption, checksummed, permission-restricted, and recorded with schema/release identity.

Keys live outside the backup destination and repository. Retention and off-site replication are environment-owned. Weekly isolated restore drills are required; a successful upload or checksum is not restoration evidence. Production backup status remains unknown until the external job supplies signed evidence.
