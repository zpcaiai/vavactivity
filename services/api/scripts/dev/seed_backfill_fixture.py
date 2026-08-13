"""Create a realistic pre-migration fixture for the last-four backfill (CHK-002).

This exists to make ``vav.cli.backfill_last_four_hmac`` provable rather than
merely plausible. It writes phone contact points the way the application wrote
them *before* migration ``20260812_0105`` existed — encrypted value, whole-number
search HMAC, and ``last_four_hmac`` left NULL — so a backfill run against this
data exercises the same path a real deployment will.

It also plants two rows the worker must refuse rather than guess at: a contact
point whose ciphertext is corrupt, and one whose plaintext holds no usable
digits. A backfill that "succeeds" on those is writing a wrong answer.

Development only. Refuses to touch anything but a local database.
"""

from __future__ import annotations

import asyncio
import os
import sys

from sqlalchemy import text

from vav.core.database import get_engine, session_factory
from vav.modules.privacy.crypto import encrypt_private, searchable_hmac

#: Deliberately includes three numbers sharing the last four digits 4321. The
#: ambiguity path is the normal case at scale, and a fixture without it would
#: let a single-candidate bug through.
PHONES = [
    "+8613800004321",
    "+8613900004321",
    "+8613700004321",
    "+8613612345678",
    "+8613687654321",
    "+8615900001111",
    "+8615900002222",
    "+8618600009999",
]


async def main() -> int:
    database_url = os.environ.get("DATABASE_URL", "")
    if not any(host in database_url for host in ("localhost", "127.0.0.1")):
        raise SystemExit("refusing to seed a fixture into a non-local database")

    created = 0
    async with session_factory() as session:
        for index, phone in enumerate(PHONES):
            email = f"backfill-fixture-{index}@example.invalid"
            user_id = await session.scalar(
                text(
                    "INSERT INTO users (email, display_email, status, email_verified_at) "
                    "VALUES (CAST(:email AS citext), CAST(:email AS varchar), 'active', now()) "
                    "ON CONFLICT (email) DO UPDATE SET updated_at = now() "
                    "RETURNING id"
                ),
                {"email": email},
            )
            await session.execute(
                text(
                    "INSERT INTO user_contact_points "
                    "  (user_id, contact_type, value_encrypted, value_hmac, status, "
                    "   verified_at, is_primary) "
                    "VALUES (:user_id, 'phone', :encrypted, :hmac, 'verified', now(), true) "
                    "ON CONFLICT (user_id, contact_type, value_hmac) DO NOTHING"
                ),
                {
                    "user_id": user_id,
                    "encrypted": encrypt_private(phone),
                    "hmac": searchable_hmac(phone),
                },
            )
            created += 1

        # Two rows the worker must skip loudly rather than fill in.
        for label, ciphertext in (
            ("corrupt", "not-a-valid-ciphertext"),
            ("no-digits", encrypt_private("not a phone number")),
        ):
            email = f"backfill-fixture-{label}@example.invalid"
            user_id = await session.scalar(
                text(
                    "INSERT INTO users (email, display_email, status, email_verified_at) "
                    "VALUES (CAST(:email AS citext), CAST(:email AS varchar), 'active', now()) "
                    "ON CONFLICT (email) DO UPDATE SET updated_at = now() "
                    "RETURNING id"
                ),
                {"email": email},
            )
            await session.execute(
                text(
                    "INSERT INTO user_contact_points "
                    "  (user_id, contact_type, value_encrypted, value_hmac, status, is_primary) "
                    "VALUES (:user_id, 'phone', :encrypted, :hmac, 'verified', true) "
                    "ON CONFLICT (user_id, contact_type, value_hmac) DO NOTHING"
                ),
                {
                    "user_id": user_id,
                    "encrypted": ciphertext,
                    "hmac": searchable_hmac(f"unusable-{label}"),
                },
            )
            created += 1

        # The fixture emulates pre-migration rows, so clear anything a write
        # path may have populated. This is the state the backfill must repair.
        await session.execute(
            text(
                "UPDATE user_contact_points SET last_four_hmac = NULL "
                "WHERE user_id IN (SELECT id FROM users WHERE email LIKE 'backfill-fixture-%')"
            )
        )
        await session.commit()

    print(f"seeded {created} phone contact points with last_four_hmac NULL")
    await get_engine().dispose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
