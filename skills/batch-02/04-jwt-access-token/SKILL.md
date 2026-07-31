---
name: vav-jwt-access-token
description: Issue and validate short-lived EdDSA access JWTs.
---

Use Ed25519 keys with `kid`, `iss`, distinct user/admin `aud`, `sub`, session ID,
issued/expiry times and auth/RBAC versions. Fail closed on algorithm, audience, key
or version mismatch; never place access tokens in localStorage.
