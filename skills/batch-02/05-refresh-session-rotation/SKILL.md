---
name: vav-refresh-session-rotation
description: Implement opaque refresh cookies, atomic rotation and family reuse detection.
---

Hash refresh tokens with a server pepper, bind them to a session family and rotate
under a row lock. Reuse of a replaced token revokes the full family. Require
Origin/CSRF validation for cookie mutation and make logout idempotent.
