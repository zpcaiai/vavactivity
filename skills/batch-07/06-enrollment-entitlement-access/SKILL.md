---
name: vav-enrollment-entitlement-access
description: Implement VAV free and entitlement-backed course enrollment and backend lesson access decisions. Use for purchased access, bundles, membership boundaries or entitlement projection.
---

# Workflow

Project active `course_access` entitlements exactly once, expand snapshotted
bundles, pin the latest published curriculum version and mirror
suspend/revoke/expire states. Free courses still create a normal enrollment.

