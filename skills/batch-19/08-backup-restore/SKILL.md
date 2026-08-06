---
name: vav-backup-restore
description: Create identified encrypted VAV backup sets and prove restoration in a disposable isolated environment.
---

Back up PostgreSQL, object storage and configuration/release identity as one set. Encrypt each artifact with AES-256-GCM outside the destination key boundary, checksum it, restrict permissions and retain off-site per policy. Run `make backup backup-verify restore-drill restore-smoke`; the drill verifies schema/table/object integrity and destroys its temporary database. Never restore over the only source, expose plaintext, call upload success restoration, or claim managed PITR without external evidence.
