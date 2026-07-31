---
name: vav-email-verification-password-recovery
description: Implement single-use email verification and password recovery.
---

Store only token hashes, expire and consume atomically, invalidate prior outstanding
tokens, rate-limit resend/recovery and keep responses enumeration-safe. Password reset
must increment auth version and revoke all sessions.
