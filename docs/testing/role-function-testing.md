# Role function testing

This local engineering gate tests the complete RBAC decision surface without
production credentials or commercial-release evidence.

Run:

```bash
make role-function-verify
```

With the local Compose API, PostgreSQL, Redis, user web and admin web running,
also execute the real registration, email verification, user session and
administrator permission-navigation flows:

```bash
make role-function-browser-test
```

The audit executes one allow-or-deny decision for every role and every
registered permission, verifies that all permission references are registered,
classifies every API operation by its authentication/permission mode, and fails
if an `/admin/` operation is unintentionally public. It is combined with the
backend identity suite and both web applications' unit and type tests. The
generated matrix is at `build/testing/role-function-matrix.json` and lists each
role's permissions and the number of API operations reachable through those
permissions. It also separates permissions currently bound to API operations
from policy-only catalog permissions, so an authorization decision is never
misreported as an implemented user-facing operation. Admin-web route,
navigation and action permission references are checked against the same
backend registry. `functional_coverage_complete` remains false while any
registered permission has no executable API binding; the per-role rows list
those policy-only grants explicitly.

The browser target is kept separate because it mutates synthetic E2E accounts.
It creates temporary no-hot-reload API and web processes on isolated ports,
executes the browser scenarios, then removes those processes and its temporary
container. PostgreSQL, Redis and Mailpit must already be available from the
local Compose stack. Do not run it concurrently with a backend test process
that resets or locks the same local database.

This gate deliberately excludes production DAST, penetration testing, physical
device UAT, production load, HA/DR, owner approval and observation windows. A
local `PASS` is functional RBAC evidence, not production certification.
