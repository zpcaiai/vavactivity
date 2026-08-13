"""Backfill ``user_contact_points.last_four_hmac`` (CHK-002).

Why this exists as a worker rather than a migration: the column is an HMAC of a
phone number's last four digits, and the stored number is encrypted. SQL cannot
derive four digits from ciphertext, so migration ``20260812_0105`` creates the
column empty and this job fills it with the decryption key in hand.

Until it runs, contact points created before that migration are simply not
findable by last-four lookup. That is the honest failure: the alternative —
guessing, or leaving the column nullable-but-populated-with-junk — would make
the lookup silently wrong rather than visibly incomplete.

Usage::

    python -m vav.cli.backfill_last_four_hmac --dry-run
    python -m vav.cli.backfill_last_four_hmac --batch-size 500 --apply

The job is resumable and idempotent: it only touches rows whose
``last_four_hmac`` is NULL or carries a stale salt version, and it commits per
batch so an interrupted run loses at most one batch of work.
"""

from __future__ import annotations

import argparse
import asyncio
from typing import Any

from sqlalchemy import text

from vav.common.exceptions import VavError
from vav.core.config import get_settings
from vav.core.database import get_engine, session_factory
from vav.modules.checkin_operations.domain import (
    CheckinRuleError,
    last_four_hmac,
    last_four_of,
    normalize_phone_digits,
)
from vav.modules.privacy.crypto import decrypt_private


def _lookup_key() -> bytes:
    """Refuse to run without a real, deployment-specific salt.

    An unsalted HMAC over four digits is a ten-thousand-entry rainbow table,
    and the repository's ``local-...-change-me`` default is no better than
    unsalted: anyone who can read this project knows it. Both cases have to
    fail loudly, because the failure they prevent — a column that looks
    protected and is not — is silent by nature.

    Empty and default are reported separately so an operator who hit this can
    tell "I forgot to set it" from "my deploy did not pick up the value I set".
    """

    settings = get_settings()
    secret = settings.checkin_last_four_hmac_key
    key = (secret.get_secret_value() if secret else "").strip()
    if not key:
        raise SystemExit(
            "CHECKIN_LAST_FOUR_HMAC_KEY is not configured. Refusing to write an unsalted "
            "last-four HMAC."
        )
    if "change-me" in key:
        raise SystemExit(
            "CHECKIN_LAST_FOUR_HMAC_KEY is still the development default shipped in this "
            "repository. A published key makes the last-four column a phone enumeration "
            "oracle; refusing to write digests under it."
        )
    return key.encode("utf-8")


async def _count_pending(session: Any, salt_version: str) -> int:
    return int(
        await session.scalar(
            text(
                "SELECT count(*) FROM user_contact_points "
                "WHERE contact_type='phone' AND value_encrypted IS NOT NULL "
                "  AND (last_four_hmac IS NULL OR last_four_hmac NOT LIKE :prefix)"
            ),
            {"prefix": f"{salt_version}:%"},
        )
        or 0
    )


async def run(*, batch_size: int, apply: bool, limit: int | None) -> int:
    settings = get_settings()
    salt_version = settings.checkin_last_four_salt_version
    key = _lookup_key()

    processed = 0
    visited = 0
    failed = 0
    #: Keyset cursor. Paging by ``id > cursor`` rather than re-running the
    #: "still pending" predicate each round is what makes this job terminate.
    #:
    #: The predicate alone looks sufficient — a row that gets a digest stops
    #: matching it — but rows that *cannot* be fixed never stop matching. They
    #: accumulate at the head of every subsequent page, so useful work per
    #: batch decays toward zero, and once undecryptable rows fill one whole
    #: batch the loop re-reads that same page forever. A cursor visits every
    #: row exactly once regardless of how many are unfixable.
    cursor: str | None = None

    async with session_factory() as session:
        pending = await _count_pending(session, salt_version)
        print(f"pending rows: {pending} (salt version {salt_version})")
        if pending == 0:
            return 0

        while True:
            if limit is not None and visited >= limit:
                break
            rows = (
                (
                    await session.execute(
                        text(
                            "SELECT id, value_encrypted FROM user_contact_points "
                            "WHERE contact_type='phone' AND value_encrypted IS NOT NULL "
                            "  AND (last_four_hmac IS NULL OR last_four_hmac NOT LIKE :prefix) "
                            # The cast is written twice on purpose: a bare
                            # ``:cursor IS NULL`` gives Postgres nothing to
                            # infer the parameter type from and it refuses to
                            # prepare the statement.
                            "  AND (CAST(:cursor AS uuid) IS NULL "
                            "       OR id > CAST(:cursor AS uuid)) "
                            "ORDER BY id LIMIT :batch"
                        ),
                        {
                            "prefix": f"{salt_version}:%",
                            "batch": batch_size,
                            "cursor": cursor,
                        },
                    )
                )
                .mappings()
                .all()
            )
            if not rows:
                break
            cursor = str(rows[-1]["id"])
            visited += len(rows)

            updates: list[dict[str, str]] = []
            for row in rows:
                try:
                    raw = decrypt_private(row["value_encrypted"])
                    digits = normalize_phone_digits(str(raw))
                    digest = last_four_hmac(
                        last_four_of(digits), key=key, salt_version=salt_version
                    )
                except (VavError, CheckinRuleError, ValueError, TypeError) as error:
                    # A row we cannot decrypt or parse is left alone and
                    # counted. Skipping loudly beats writing a wrong digest.
                    #
                    # ``VavError`` belongs in this tuple because that is what
                    # ``decrypt_private`` raises on an unreadable ciphertext,
                    # and unreadable ciphertext is precisely the condition this
                    # job exists to survive. Without it one corrupt row two
                    # thousand rows in aborts the whole backfill and every row
                    # after it stays unfindable — the opposite of resumable.
                    failed += 1
                    print(f"  skip {row['id']}: {type(error).__name__}")
                    continue
                updates.append({"id": str(row["id"]), "digest": digest})

            if not updates:
                # Nothing fixable in this page. The cursor has already moved
                # past it, so the next round makes progress either way.
                if len(rows) < batch_size:
                    break
                continue

            if apply:
                for update in updates:
                    await session.execute(
                        text(
                            "UPDATE user_contact_points SET last_four_hmac=:digest "
                            "WHERE id=CAST(:id AS uuid)"
                        ),
                        update,
                    )
                await session.commit()
            processed += len(updates)
            print(f"  {'wrote' if apply else 'would write'} {len(updates)} (total {processed})")

            if len(rows) < batch_size:
                break

    verb = "wrote" if apply else "would write"
    print(f"done: visited {visited}, {verb} {processed}, unfixable {failed}")
    if failed:
        # Unfixable rows stay unfindable by last-four lookup. That is a data
        # problem for a human, not something a re-run will clear, so it is
        # stated rather than buried in the per-row log above.
        print(
            f"note: {failed} row(s) could not be decrypted or parsed and were left untouched; "
            "they remain unfindable by last-four lookup until the underlying value is repaired"
        )
    if not apply:
        print("dry run — re-run with --apply to persist")
    await get_engine().dispose()
    return processed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--limit", type=int, default=None, help="stop after N rows")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--apply", action="store_true", help="persist the computed digests")
    group.add_argument("--dry-run", action="store_true", help="default; change nothing")
    args = parser.parse_args()

    if not 1 <= args.batch_size <= 5000:
        raise SystemExit("--batch-size must be between 1 and 5000")

    asyncio.run(run(batch_size=args.batch_size, apply=args.apply, limit=args.limit))


if __name__ == "__main__":
    main()
