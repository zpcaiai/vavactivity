# PATCHES — changes required to existing repository files (batch P4)

Nothing in `batch_p4/` edits an existing file. This document lists every change
that must be applied by hand for the two new modules to work, in the order a
deploy would apply them, followed by the repository assumptions a reviewer
should verify before merging.

## Current checkout status (2026-08-13)

This file began as the batch handoff. The current checkout has now applied the
listed repository patches:

| Item | Status | Current evidence |
|---|---|---|
| Settings and deployment variables | DONE | `Settings`, deployment validation and environment templates contain the feature flags and secret references. |
| Phone last-four write path | DONE | The privacy contact-point route writes `last_four_hmac` when configured and fails open to `NULL` when the optional lookup key is absent. |
| Migration chain | DONE | A clean database upgrades through the single `20260813_0110` head. |
| Models, routers and permissions | DONE | Both modules are registered and their admin routes use server-side permissions. |
| Registration capacity lifecycle | DONE | Registration reserves a held seat or queue place; confirmation moves the hold; rejection, cancellation and activity cancellation release it. Historical registrations are backfilled with ownership/event state. |
| Last-four backfill executable | DONE | `vav.cli.backfill_last_four_hmac` provides audited dry-run/apply batches. |
| Background backfill consumer | DONE | Celery Beat claims one queued run at a time with `FOR UPDATE SKIP LOCKED`, invokes the resumable CLI, and records completion or a safe failure type. |

Local verification for this closure: 422 backend tests passed with 1 skipped,
Ruff and targeted strict mypy passed, a clean migration reached `0110`, and the
runtime smoke gate passed. These results do not certify production deployment
or external provider behavior.

---

## 1. `vav/core/config.py` — add the settings fields

Paste the `Field(...)` lines from `CONFIG_ADDITIONS.py` into `Settings`. Twelve
fields for `checkin_operations`, five for `capacity_guard`.

Two of them (`checkin_last_four_hmac_key`, `checkin_token_signing_key`) have an
empty default that the service treats as "feature unavailable, return 503". Do
**not** give them a real default value to make local development easier — an
unsalted HMAC over four digits is a rainbow table over the entire member base,
and a shared default would ship one.

---

## 2. `vav/models/identity.py` (wherever `UserContactPoint` is declared) — one new column

Migration `20260812_0105` adds `user_contact_points.last_four_hmac`. The model
must document it, or the ORM and the schema drift apart:

```python
    #: Salted HMAC of the last four digits only. Narrowing aid for the onsite
    #: check-in lookup (CHK-002) — NOT an identity proof, and never used alone
    #: to resolve a person. NULL means "created before 20260812_0105"; such a
    #: row simply does not appear in a last-four search.
    last_four_hmac: Mapped[str | None] = mapped_column(String(128))
```

Add it next to the existing `value_hmac` column so the distinction between "HMAC
of the whole number" and "HMAC of the last four" is visible at a glance.

---

## 3. The phone write path — populate the new column

This is the one behavioural change to existing code. Wherever a phone contact
point is created or updated (phone verification, profile edit, admin correction),
the write currently computes `value_hmac` from the plaintext; it must now compute
both. `checkin_operations.service.contact_point_write_values` exists so this is
one call:

```python
from vav.modules.checkin_operations.service import contact_point_write_values

values = contact_point_write_values(raw_phone)
# INSERT ... value_encrypted=:enc, value_hmac=:value_hmac, last_four_hmac=:last_four_hmac
```

If `CHECKIN_LAST_FOUR_HMAC_KEY` is unset the helper raises a 503-shaped
`VavError`. Decide deliberately which you want at the call site:

* **Preferred:** catch it and write `last_four_hmac = NULL`. The contact point is
  still created; it is merely not findable by last-four until the key is
  configured and the backfill runs.
* Letting it propagate would make phone verification fail on a deployment that
  has not enabled the check-in feature at all, which is the wrong coupling.

---

## 4. Migrations — chain and ordering

Copy `migration_0105_checkin_operations.py` and `migration_0106_capacity_guard.py`
into `migrations/` under their revision names.

`20260812_0105` declares `down_revision = "20260812_0104"`. **Verify that
`20260812_0104` exists in the target branch.** This checkout contains only
`…_0095` and `…_0096`; revisions `0097`–`0101` were produced by earlier batches
(P1/P2) and `0102`–`0104` are assumed to come from the batch immediately before
this one. If the real predecessor differs, change `down_revision` in `0105` —
that is the only edit needed, and `scripts/verify_migrations.py` will tell you
immediately if the chain has a hole or a second head.

---

## 5. `vav/models/__init__.py` — register the new model modules

Add the two new model modules so their tables join `Base.metadata` (needed by
`alembic check`/autogenerate and by any metadata-driven tooling):

```python
from vav.models import capacity_guard as capacity_guard  # noqa: F401
from vav.models import checkin_operations as checkin_operations  # noqa: F401
```

after copying `models_checkin_operations.py` → `vav/models/checkin_operations.py`
and `models_capacity_guard.py` → `vav/models/capacity_guard.py`.

---

## 6. Router registration

Copy the module directories to `vav/modules/checkin_operations/` and
`vav/modules/capacity_guard/`, then register four routers wherever the existing
modules are wired (`vav/api/main.py` or the router aggregator):

```python
from vav.modules.capacity_guard.admin_router import router as capacity_guard_admin_router
from vav.modules.capacity_guard.router import router as capacity_guard_router
from vav.modules.checkin_operations.admin_router import router as checkin_operations_admin_router
from vav.modules.checkin_operations.router import router as checkin_operations_router
```

Both admin routers use the `/admin` prefix and both member routers use
`/account`, matching `post_event`.

---

## 7. Permission seeding

Create the ten permission codes listed in `PERMISSIONS.md` through the existing
seeding step. Until they exist, every admin route in both modules returns 403 —
which is the correct failure, but it will look like a wiring bug if nobody reads
this section.

---

## 8. The registration flow must call the capacity guard

`capacity_guard` is inert until the registration flow calls it. Three call sites,
all inside the transaction that already exists:

| When | Call | Effect |
|---|---|---|
| A member submits a registration | `reserve_seat(...)` | Takes a **held** seat, or creates a waitlist position, or raises `CAPACITY_FULL`. |
| Payment or approval lands | `confirm_reservation(...)` | Moves the seat from held to confirmed. |
| Cancellation, payment expiry, refund | `release_seats(...)` | Returns the seat **and runs a promotion round in the same transaction**. |

Two things to get right:

* `reserve_seat` needs a client-supplied `idempotency_key`. Reuse the one the
  registration endpoint already accepts if there is one; do not generate it
  server-side per request, or a double-tap takes two seats.
* Do not also decrement any pre-existing capacity counter in the registration
  code. Two writers on the same number is how counters drift; the counter row is
  now the single source of truth, and the CHECK constraint on it will reject the
  second writer's arithmetic sooner or later — probably at 19:00 on an event
  night.

---

## 9. The `last_four_hmac` backfill is a job, not a migration

Migration `0105` backfills **nothing**, and the header comment in it explains
why: the stored phone value is ciphertext, so no SQL statement can derive its
last four digits. The migration cannot do this; only a worker holding the privacy
decryption key can.

`POST /admin/checkin/last-four-backfill` books such a run
(`checkin_last_four_backfill_runs`) and emits
`checkin.last_four_backfill.requested.v1`. **The worker that consumes that event
is not in this batch.** Until it is written, operators have two options, and both
are legitimate:

* **Do nothing.** The column populates naturally as members re-verify their phone
  numbers. Slower, needs no bulk decryption, no maintenance window.
* **Write the worker.** It reads `batch_size` rows with `last_four_hmac IS NULL`,
  decrypts each `value_encrypted`, and writes
  `last_four_hmac(last_four_of(plaintext), key=..., salt_version=...)`. It should
  run once, under an audit note, and never log a plaintext value.

Until one of those happens, a member whose contact row predates the migration is
simply not findable by last-four. That is the honest failure mode — the operator
falls back to the QR credential.

---

## 10. `activity_checkin_events.action` vocabulary

The service writes only `'check_in'` and `'revoke'` to the existing
`activity_checkin_events` table, on the assumption that those two values are
already permitted by whatever CHECK constraint or application convention governs
that column. The operational states this module introduces (`duplicate_scan`,
`reinstate`, `lookup`, `select_candidate`) go to the module's own
`checkin_operation_events` table instead, precisely so that no existing
constraint has to be widened.

**If the existing vocabulary uses different spellings** (`checkin` rather than
`check_in`, say), fix the four `INSERT INTO activity_checkin_events` statements in
`checkin_operations/service.py`. Note that `post_event/service.py` already reads
`action='check_in'`, which is where the spelling used here comes from.

---

# Repository assumptions a reviewer should double-check

These are things this batch could not verify from the files available in this
checkout. Each one is load-bearing; each one is a one-line fix if it is wrong.

1. **`activity_ticket_types` exists and its seat cap column is named `capacity`.**
   Used by `migration_0106`'s counter seeding (`COALESCE(t.capacity, 0)`) and by
   every foreign key in that migration. `activity_registrations.ticket_type_id`
   implies the table; the column name is the guess. If it is `quota`,
   `total_quantity` or similar, change the one `SELECT` in the migration.
2. **`activity_sessions(starts_at, ends_at)`.** Read by
   `_session_window` to classify the check-in window. If the column names differ,
   the check-in window silently becomes "always in window" — the code treats a
   missing row as "no window configured" rather than failing, so this one will
   *not* announce itself. Worth an explicit look.
3. **`activities.starts_at`.** Used to clamp promotion-offer deadlines so an
   offer never outlives its event. If absent, the clamp degrades to the plain
   TTL.
4. **`user_contact_points.status` uses `'verified'`.** The lookup query requires
   it, so an unverified number never resolves anybody. If the vocabulary is
   different (`'active'`, `'confirmed'`), the lookup returns nothing at all —
   loudly, at least.
5. **`activity_participant_profiles.display_name`.** Copied from
   `post_event/service.py::_load_attendance`, including the
   `'member-' || left(user_id::text, 8)` fallback. Only ever used to derive a
   single masked initial.
6. **`vav.modules.privacy.crypto.searchable_hmac(value: str) -> str`.** Called in
   `contact_point_write_values` to keep `value_hmac` computed exactly the way the
   existing write path computes it. If its signature takes a purpose/context
   argument, pass the same one the existing phone write uses — otherwise the two
   HMACs will not match and phone lookup breaks.
7. **`outbox_events(topic, aggregate_type, aggregate_id, payload jsonb)`.** Copied
   verbatim from `post_event/service.py`.
8. **`VavError(code, message, status_code=..., details=[...])` with `details` as a
   list.** Both services wrap a rule's mapping in a single-element list, matching
   `post_event/service.py::_fail`.
9. **`AuthenticatedPrincipal.user.id`** and the
   `get_database_session` / `require_authenticated_user` / `require_permission`
   dependency names, all copied from `post_event`'s routers.
10. **`activity_registrations` has no per-registration seat count.** `reserve_seat`
    therefore takes `seats` from the request and the `0106` backfill assumes one
    seat per existing waitlisted registration. If group registrations carry a
    party size elsewhere, the backfill should read it — a backfilled entry with
    the wrong seat count can block a queue (the default no-skip promotion policy
    is deliberate about that).
11. **`checkin_operation_events.metadata` as a column name.** `metadata` is
    reserved on SQLAlchemy's declarative class, which is why the model maps it as
    `metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, ...)`. The
    same pattern appears in `activity_capacity_events`. If the house style is to
    name such columns `metadata_json` in SQL too, rename in both the migration
    and the model.
12. **Ruff/lint configuration.** The two service modules and both routers carry
    `# ruff: noqa: E501` (and `B008` on routers) exactly as `post_event` does; if
    the project config has since changed, drop the pragmas.
