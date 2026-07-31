---
name: vav-user-registration-login
description: Implement secure registration, login, logout, account and session APIs.
---

Normalize email without losing the display form, apply Argon2id policy, use generic
credential failures, lock repeated failures and never reveal account existence.
Require server-side account state checks on every authenticated request.
