# ruff: noqa: E501

"""Separate bounded zero capacity from unlimited inventory.

``20260812_0106`` originally overloaded ``capacity = 0`` to mean unlimited.
That makes a finite, sold-out ticket type indistinguishable from one with no
ceiling, and its original inner join also omitted unlimited SKUs that correctly
had no ``inventory_items`` row. The corrected 0106 handles fresh databases;
this revision repairs databases that already recorded the older revision.

The SKU is the canonical owner of ``inventory_policy``. Inventory rows provide
the bounded arithmetic only. Historical confirmed and held seats are never
reduced to make the constraint pass: a bounded counter is raised to at least
the committed count and every corrective difference is written to the existing
append-only capacity event log.

Revision ID: 20260813_0111
Revises: 20260813_0110
"""

import re

from alembic import op

revision = "20260813_0111"
down_revision = "20260813_0110"
branch_labels = None
depends_on = None


def _split_statements(script: str) -> list[str]:
    """Split SQL without breaking comments, strings or dollar-quoted blocks."""

    statements: list[str] = []
    buffer: list[str] = []
    index = 0
    length = len(script)
    while index < length:
        char = script[index]
        pair = script[index : index + 2]
        if pair == "--":
            end = script.find("\n", index)
            index = length if end == -1 else end
            continue
        if pair == "/*":
            end = script.find("*/", index + 2)
            index = length if end == -1 else end + 2
            continue
        if char == "'":
            buffer.append(char)
            index += 1
            while index < length:
                buffer.append(script[index])
                if script[index] == "'":
                    if script[index : index + 2] == "''":
                        buffer.append(script[index + 1])
                        index += 2
                        continue
                    index += 1
                    break
                index += 1
            continue
        if char == "$":
            match = re.match(r"\$[A-Za-z_]*\$", script[index:])
            if match:
                tag = match.group(0)
                end = script.find(tag, index + len(tag))
                stop = length if end == -1 else end + len(tag)
                buffer.append(script[index:stop])
                index = stop
                continue
        if char == ";":
            statements.append("".join(buffer))
            buffer = []
            index += 1
            continue
        buffer.append(char)
        index += 1
    statements.append("".join(buffer))
    return [item.strip() for item in statements if item.strip()]


def _run(script: str) -> None:
    for statement in _split_statements(script):
        op.execute(statement)


def upgrade() -> None:
    _run(
        """
        ALTER TABLE activity_capacity_counters
          ADD COLUMN IF NOT EXISTS is_unlimited BOOLEAN NOT NULL DEFAULT false;

        -- Fresh databases already have the named explicit-mode constraint.
        -- Older 0106 installs have an automatically named CHECK whose text is
        -- `capacity = 0 OR ...`; remove either shape before correcting rows.
        ALTER TABLE activity_capacity_counters
          DROP CONSTRAINT IF EXISTS activity_capacity_counters_not_oversold;
        ALTER TABLE activity_capacity_counters
          DROP CONSTRAINT IF EXISTS activity_capacity_counters_unlimited_zero;

        DO $drop_legacy_capacity_check$
        DECLARE
          legacy_name TEXT;
        BEGIN
          FOR legacy_name IN
            SELECT conname
              FROM pg_constraint
             WHERE conrelid = 'activity_capacity_counters'::regclass
               AND contype = 'c'
               AND pg_get_constraintdef(oid) LIKE '%capacity = 0%'
               AND pg_get_constraintdef(oid) LIKE '%confirmed_seats%'
               AND pg_get_constraintdef(oid) LIKE '%held_seats%'
          LOOP
            EXECUTE format(
              'ALTER TABLE activity_capacity_counters DROP CONSTRAINT %I',
              legacy_name
            );
          END LOOP;
        END
        $drop_legacy_capacity_check$;

        -- Materialize the decision once so the audit row and the update cannot
        -- disagree. Existing operator adjustments are preserved; otherwise the
        -- bounded ceiling is resynchronized to catalog arithmetic. Rows omitted
        -- by the old inner join are represented by NULL before_* values.
        CREATE TEMP TABLE vav_0111_capacity_targets ON COMMIT DROP AS
        WITH registration_counts AS (
          SELECT ticket_type_id,
                 count(*) FILTER (WHERE status = 'confirmed') AS confirmed,
                 count(*) FILTER (WHERE status IN ('pending_approval','approved_pending_payment',
                                                   'pending_payment','payment_processing')) AS held,
                 count(*) FILTER (WHERE status = 'waitlisted') AS waitlisted
            FROM activity_registrations
           GROUP BY ticket_type_id
        ), base AS (
          SELECT t.id AS ticket_type_id,
                 t.activity_id,
                 c.capacity AS before_capacity,
                 c.is_unlimited AS before_is_unlimited,
                 COALESCE(c.confirmed_seats, counts.confirmed, 0)::INTEGER AS confirmed_seats,
                 COALESCE(c.held_seats, counts.held, 0)::INTEGER AS held_seats,
                 COALESCE(c.waitlisted_count, counts.waitlisted, 0)::INTEGER AS waitlisted_count,
                 sku.inventory_policy,
                 (sku.inventory_policy = 'unlimited') AS target_is_unlimited,
                 CASE
                   WHEN sku.inventory_policy = 'unlimited' THEN 0
                   ELSE GREATEST(0, COALESCE(inv.total_capacity, 0)
                        - COALESCE(inv.safety_stock, 0)
                        + CASE WHEN COALESCE(inv.overselling_allowed, false)
                               THEN COALESCE(inv.oversell_limit, 0) ELSE 0 END)
                 END AS catalogue_capacity,
                 (inv.id IS NULL) AS inventory_row_missing,
                 (c.ticket_type_id IS NOT NULL AND EXISTS (
                    SELECT 1
                      FROM activity_capacity_events event
                     WHERE event.ticket_type_id = t.id
                       AND event.event_type = 'capacity_adjusted'
                       AND event.actor_id IS NOT NULL
                 )) AS manual_capacity_preserved
            FROM activity_ticket_types t
            JOIN product_skus sku ON sku.id = t.catalog_sku_id
            LEFT JOIN inventory_items inv ON inv.sku_id = sku.id
            LEFT JOIN activity_capacity_counters c ON c.ticket_type_id = t.id
            LEFT JOIN registration_counts counts ON counts.ticket_type_id = t.id
        )
        SELECT base.*,
               CASE
                 WHEN target_is_unlimited THEN 0
                 WHEN manual_capacity_preserved THEN
                   GREATEST(before_capacity, confirmed_seats + held_seats)
                 ELSE GREATEST(catalogue_capacity, confirmed_seats + held_seats)
               END AS target_capacity
          FROM base;

        -- Old 0106 omitted unlimited SKUs without inventory rows. Insert every
        -- missing counter now. Non-unlimited missing inventory is a bounded zero
        -- cap and therefore fails closed; committed historical seats still raise
        -- the stored cap rather than being erased.
        INSERT INTO activity_capacity_counters
          (ticket_type_id, activity_id, capacity, is_unlimited,
           confirmed_seats, held_seats, waitlisted_count)
        SELECT ticket_type_id, activity_id, target_capacity, target_is_unlimited,
               confirmed_seats, held_seats, waitlisted_count
          FROM vav_0111_capacity_targets
         WHERE before_capacity IS NULL
        ON CONFLICT (ticket_type_id) DO NOTHING;

        INSERT INTO activity_capacity_events
          (activity_id, ticket_type_id, event_type, seats, reason, metadata)
        SELECT activity_id,
               ticket_type_id,
               'capacity_adjusted',
               CASE WHEN before_capacity IS NULL
                    THEN target_capacity - catalogue_capacity
                    ELSE target_capacity - before_capacity END,
               CASE WHEN before_capacity IS NULL
                    THEN 'corrective backfill: bounded committed seats exceeded the catalogue ceiling'
                    ELSE 'corrective migration: capacity mode and ceiling synchronized without reducing committed seats' END,
               jsonb_build_object(
                 'before_capacity', before_capacity,
                 'after_capacity', target_capacity,
                 'before_is_unlimited', before_is_unlimited,
                 'after_is_unlimited', target_is_unlimited,
                 'catalogue_capacity', catalogue_capacity,
                 'confirmed_seats', confirmed_seats,
                 'held_seats', held_seats,
                 'inventory_policy', inventory_policy,
                 'inventory_row_missing', inventory_row_missing,
                 'manual_capacity_preserved', manual_capacity_preserved,
                 'migration', '20260813_0111'
               )
          FROM vav_0111_capacity_targets
         WHERE (
                 (
                   before_capacity IS NOT NULL
                   AND (
                     before_capacity IS DISTINCT FROM target_capacity
                     OR before_is_unlimited IS DISTINCT FROM target_is_unlimited
                   )
                 )
                 OR (
                   before_capacity IS NULL
                   AND NOT target_is_unlimited
                   AND target_capacity > catalogue_capacity
                 )
               )
           AND NOT EXISTS (
                 SELECT 1
                   FROM activity_capacity_events prior
                  WHERE prior.ticket_type_id = vav_0111_capacity_targets.ticket_type_id
                    AND prior.event_type = 'capacity_adjusted'
                    AND prior.metadata->>'migration' = '20260813_0111'
               );

        UPDATE activity_capacity_counters counter
           SET capacity = target.target_capacity,
               is_unlimited = target.target_is_unlimited,
               version = counter.version + 1,
               updated_at = now()
          FROM vav_0111_capacity_targets target
         WHERE counter.ticket_type_id = target.ticket_type_id
           AND target.before_capacity IS NOT NULL
           AND (
             counter.capacity IS DISTINCT FROM target.target_capacity
             OR counter.is_unlimited IS DISTINCT FROM target.target_is_unlimited
           );

        ALTER TABLE activity_capacity_counters
          ADD CONSTRAINT activity_capacity_counters_not_oversold
          CHECK (is_unlimited OR confirmed_seats + held_seats <= capacity);
        ALTER TABLE activity_capacity_counters
          ADD CONSTRAINT activity_capacity_counters_unlimited_zero
          CHECK (NOT is_unlimited OR capacity = 0);
        """
    )


def downgrade() -> None:
    # Counter and audit backfills are deliberately retained. Reversing them
    # would delete operational evidence and could recreate missing counters.
    # The old application cannot represent finite-zero separately, so only the
    # schema column is removed when stepping back to 0110.
    _run(
        """
        ALTER TABLE activity_capacity_counters
          DROP CONSTRAINT IF EXISTS activity_capacity_counters_unlimited_zero;
        ALTER TABLE activity_capacity_counters
          DROP CONSTRAINT IF EXISTS activity_capacity_counters_not_oversold;
        ALTER TABLE activity_capacity_counters
          DROP COLUMN IF EXISTS is_unlimited;
        ALTER TABLE activity_capacity_counters
          ADD CONSTRAINT activity_capacity_counters_not_oversold
          CHECK (capacity = 0 OR confirmed_seats + held_seats <= capacity);
        """
    )
