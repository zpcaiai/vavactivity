---
name: vav-check-in-operations
description: Build VAV signed QR and manual activity check-in, duplicate protection, revocation and attendance views. Use whenever activity passes, scanning or attendance operations are requested.
---

# Workflow

Issue signed, short-lived credentials containing only random references and
expiry. Check confirmed registration, scope and window. Return the original
attendance for duplicates. Append revoke events instead of deleting check-ins.
Keep payment, profile and form data out of staff DTOs.
