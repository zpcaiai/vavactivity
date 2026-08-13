# ruff: noqa: E501

"""Transactional capacity counters, waitlist positions and promotion offers.

Covers ACT-003.

Revision ID: 20260812_0106
Revises: 20260812_0105
"""

import re

from alembic import op

revision = "20260812_0106"
down_revision = "20260812_0105"
branch_labels = None
depends_on = None


def _split_statements(script: str) -> list[str]:
    """Split a SQL script on statement boundaries.

    A naive ``script.split(";")`` breaks on any semicolon, including ones
    inside a ``--`` comment or a string literal — which silently turns the
    remainder of a comment into a bogus statement. Postgres then fails on
    something like ``syntax error at or near "it"``, pointing at a line that
    looks perfectly fine.

    This walks the script instead, skipping over line comments, block
    comments, single-quoted strings and dollar-quoted bodies.
    """

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
        -- One row per ticket type: the single object every seat decision locks.
        -- Counting registration rows under a lock would mean locking a growing
        -- set on every reservation and turning the door into a convoy; one row
        -- makes the critical section constant-cost.
        --
        -- The CHECK is the point of this table. Application code takes the row
        -- lock, but a guard that lives only in application code is one
        -- forgotten lock away from an oversold event; this constraint turns
        -- that bug into an IntegrityError instead of a full room.
        CREATE TABLE activity_capacity_counters (
          ticket_type_id UUID PRIMARY KEY REFERENCES activity_ticket_types(id),
          activity_id UUID NOT NULL REFERENCES activities(id),
          -- The mode is explicit. A finite ticket type may legitimately have a
          -- zero cap (sold out); unlimited is not inferred from the number.
          capacity INTEGER NOT NULL DEFAULT 0,
          is_unlimited BOOLEAN NOT NULL DEFAULT false,
          confirmed_seats INTEGER NOT NULL DEFAULT 0,
          held_seats INTEGER NOT NULL DEFAULT 0,
          waitlisted_count INTEGER NOT NULL DEFAULT 0,
          waitlist_capacity INTEGER,
          sales_state VARCHAR(16) NOT NULL DEFAULT 'open',
          version INTEGER NOT NULL DEFAULT 1,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CHECK (capacity >= 0),
          CHECK (confirmed_seats >= 0),
          CHECK (held_seats >= 0),
          CHECK (waitlisted_count >= 0),
          CONSTRAINT activity_capacity_counters_not_oversold
            CHECK (is_unlimited OR confirmed_seats + held_seats <= capacity),
          CONSTRAINT activity_capacity_counters_unlimited_zero
            CHECK (NOT is_unlimited OR capacity = 0),
          CHECK (sales_state IN ('open','closed','suspended'))
        );
        CREATE INDEX activity_capacity_counters_activity_idx
          ON activity_capacity_counters (activity_id);

        -- The unique idempotency key is what makes a double-tapped
        -- registration take one seat instead of two.
        CREATE TABLE activity_capacity_reservations (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          idempotency_key VARCHAR(128) NOT NULL,
          activity_id UUID NOT NULL REFERENCES activities(id),
          ticket_type_id UUID NOT NULL REFERENCES activity_ticket_types(id),
          registration_id UUID NOT NULL REFERENCES activity_registrations(id),
          user_id UUID NOT NULL REFERENCES users(id),
          seats INTEGER NOT NULL DEFAULT 1,
          outcome VARCHAR(16) NOT NULL,
          waitlist_entry_id UUID,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (idempotency_key),
          CHECK (seats >= 1),
          CHECK (outcome IN ('fits','waitlist'))
        );
        CREATE INDEX activity_capacity_reservations_registration_idx
          ON activity_capacity_reservations (registration_id);

        CREATE TABLE activity_waitlist_positions (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          activity_id UUID NOT NULL REFERENCES activities(id),
          ticket_type_id UUID NOT NULL REFERENCES activity_ticket_types(id),
          registration_id UUID NOT NULL REFERENCES activity_registrations(id),
          user_id UUID NOT NULL REFERENCES users(id),
          seats INTEGER NOT NULL DEFAULT 1,
          priority INTEGER NOT NULL DEFAULT 0,
          status VARCHAR(16) NOT NULL DEFAULT 'waiting',
          joined_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          offered_at TIMESTAMPTZ,
          resolved_at TIMESTAMPTZ,
          version INTEGER NOT NULL DEFAULT 1,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (registration_id),
          CHECK (seats >= 1),
          CHECK (status IN ('waiting','offered','accepted','declined','expired','withdrawn')),
          CHECK (status <> 'offered' OR offered_at IS NOT NULL)
        );
        -- Exactly the promotion order the domain computes, so the planner's
        -- query and the pure sort agree without an extra in-memory pass.
        CREATE INDEX activity_waitlist_positions_order_idx
          ON activity_waitlist_positions (ticket_type_id, priority DESC, joined_at, registration_id)
          WHERE status IN ('waiting','offered');

        CREATE TABLE activity_waitlist_promotion_offers (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          activity_id UUID NOT NULL REFERENCES activities(id),
          ticket_type_id UUID NOT NULL REFERENCES activity_ticket_types(id),
          waitlist_entry_id UUID NOT NULL REFERENCES activity_waitlist_positions(id) ON DELETE CASCADE,
          registration_id UUID NOT NULL REFERENCES activity_registrations(id),
          seats INTEGER NOT NULL DEFAULT 1,
          round_number INTEGER NOT NULL,
          offered_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          -- NOT NULL: an offer without a deadline holds a seat forever on
          -- behalf of somebody who stopped reading their notifications.
          expires_at TIMESTAMPTZ NOT NULL,
          state VARCHAR(16) NOT NULL DEFAULT 'pending',
          notified_at TIMESTAMPTZ,
          responded_at TIMESTAMPTZ,
          dedupe_key VARCHAR(255) NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (dedupe_key),
          CHECK (seats >= 1),
          CHECK (round_number >= 1),
          CHECK (expires_at > offered_at),
          CHECK (state IN ('pending','accepted','declined','expired','cancelled')),
          CHECK (state = 'pending' OR responded_at IS NOT NULL)
        );
        -- The sweeper's query: pending offers past their deadline, oldest first.
        CREATE INDEX activity_waitlist_promotion_offers_due_idx
          ON activity_waitlist_promotion_offers (expires_at) WHERE state = 'pending';
        CREATE INDEX activity_waitlist_promotion_offers_registration_idx
          ON activity_waitlist_promotion_offers (registration_id, offered_at DESC);

        -- Append-only. This is what answers "the room was full, why does the
        -- counter say 3 free" after the fact.
        CREATE TABLE activity_capacity_events (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          activity_id UUID NOT NULL REFERENCES activities(id),
          ticket_type_id UUID NOT NULL REFERENCES activity_ticket_types(id),
          registration_id UUID REFERENCES activity_registrations(id),
          event_type VARCHAR(32) NOT NULL,
          seats INTEGER NOT NULL DEFAULT 0,
          actor_id UUID REFERENCES users(id),
          reason TEXT,
          metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
          occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CHECK (event_type IN ('seat_held','seat_confirmed','seat_released','refused',
                                'capacity_adjusted','sales_state_changed','promotion_aborted')),
          CHECK (event_type <> 'capacity_adjusted' OR reason IS NOT NULL),
          CHECK (event_type <> 'sales_state_changed' OR reason IS NOT NULL)
        );
        CREATE INDEX activity_capacity_events_ticket_type_idx
          ON activity_capacity_events (ticket_type_id, occurred_at DESC);
        """
    )

    # Seed one counter per existing ticket type from the registrations that
    # already exist. Two deliberate choices:
    #
    # * ``confirmed`` counts as a confirmed seat; the in-flight statuses
    #   (pending_payment, payment_processing, pending_approval,
    #   approved_pending_payment) count as *held*. Counting them as free is the
    #   classic oversell - fifty people on a payment page all succeed.
    # * ``started`` is NOT counted. It is an abandoned form, not a seat, and
    #   counting it would make every event look full.
    #
    # NOTE: `activity_ticket_types` has no `capacity` column in this schema.
    # Capacity is owned by the catalog inventory system, reached through
    # `activity_ticket_types.catalog_sku_id`. Seeding COALESCE(t.capacity, 0)
    # would create a counter claiming every ticket type has zero seats, which
    # reads as "sold out" everywhere.
    #
    # The cap is computed exactly the way the catalog computes it in
    # `catalog.inventory.available_quantity`: an oversell allowance is part of
    # the ceiling, not an exception to it. An earlier version of this migration
    # used bare `total_capacity`, which is *stricter than the platform's own
    # rule* — it rejected a state the inventory model explicitly permits, and
    # the whole migration aborted on any deployment that had ever oversold.
    #
    # An `unlimited` sku maps to ``is_unlimited=true`` and a numeric placeholder
    # of 0. The flag matters: a finite zero-cap sku is sold out. Filtering on
    # `total_capacity IS NOT NULL` was never the same test, and unlimited SKUs
    # normally have no inventory row at all.
    op.execute(
        """
        INSERT INTO activity_capacity_counters
          (ticket_type_id, activity_id, capacity, is_unlimited,
           confirmed_seats, held_seats, waitlisted_count)
        SELECT t.id, t.activity_id,
               -- Never below what is already committed. Historical oversell is
               -- a fact: those people hold seats and will arrive. Clamping the
               -- counter down instead would tell operations fewer people are
               -- coming than actually are — someone shows up and is not on the
               -- list. The discrepancy is recorded below rather than erased.
               CASE WHEN derived.is_unlimited THEN 0
                    ELSE GREATEST(derived.cap, derived.confirmed + derived.held) END,
               derived.is_unlimited,
               derived.confirmed, derived.held, derived.waitlisted
        FROM activity_ticket_types t
        -- The SKU owns the inventory policy. Unlimited SKUs normally have no
        -- inventory row at all, so an inner join here used to omit their
        -- counters completely. A missing row for any bounded policy now fails
        -- closed as a finite zero-cap counter instead of becoming unlimited.
        JOIN product_skus sku ON sku.id = t.catalog_sku_id
        LEFT JOIN inventory_items inv ON inv.sku_id = sku.id
        LEFT JOIN (
          SELECT ticket_type_id,
                 count(*) FILTER (WHERE status = 'confirmed') AS confirmed,
                 count(*) FILTER (WHERE status IN ('pending_approval','approved_pending_payment',
                                                   'pending_payment','payment_processing')) AS held,
                 count(*) FILTER (WHERE status = 'waitlisted') AS waitlisted
          FROM activity_registrations
          GROUP BY ticket_type_id
        ) counts ON counts.ticket_type_id = t.id
        CROSS JOIN LATERAL (
          SELECT
            CASE
              WHEN sku.inventory_policy = 'unlimited' THEN 0
              ELSE GREATEST(0, COALESCE(inv.total_capacity, 0)
                   - COALESCE(inv.safety_stock, 0)
                   + CASE WHEN inv.overselling_allowed
                          THEN COALESCE(inv.oversell_limit, 0) ELSE 0 END)
            END AS cap,
            (sku.inventory_policy = 'unlimited') AS is_unlimited,
            COALESCE(counts.confirmed, 0) AS confirmed,
            COALESCE(counts.held, 0) AS held,
            COALESCE(counts.waitlisted, 0) AS waitlisted
        ) derived
        -- An uncapped sku still gets a counter with an explicit mode, so the
        -- guard can track seats without closing sales.
        ON CONFLICT (ticket_type_id) DO NOTHING;
        """
    )

    # Every ticket type whose committed seats exceeded the catalog's ceiling is
    # written to the event log. The counter above is now internally consistent,
    # and that consistency must not be mistaken for "nothing was wrong here":
    # this row is how an operator finds the events that need a decision.
    op.execute(
        """
        INSERT INTO activity_capacity_events
          (activity_id, ticket_type_id, event_type, seats, reason, metadata)
        SELECT c.activity_id, c.ticket_type_id, 'capacity_adjusted',
               c.capacity - derived.cap,
               'backfill: committed seats exceeded the catalogue ceiling; capacity '
               'raised to match reality rather than reducing recorded registrations',
               jsonb_build_object(
                 'catalogue_capacity', derived.cap,
                 'seeded_capacity', c.capacity,
                 'confirmed_seats', c.confirmed_seats,
                 'held_seats', c.held_seats,
                 'migration', '20260812_0106'
               )
        FROM activity_capacity_counters c
        JOIN activity_ticket_types t ON t.id = c.ticket_type_id
        JOIN product_skus sku ON sku.id = t.catalog_sku_id
        LEFT JOIN inventory_items inv ON inv.sku_id = sku.id
        CROSS JOIN LATERAL (
          SELECT CASE
                   WHEN sku.inventory_policy = 'unlimited' THEN 0
                   ELSE GREATEST(0, COALESCE(inv.total_capacity, 0)
                        - COALESCE(inv.safety_stock, 0)
                        + CASE WHEN inv.overselling_allowed
                               THEN COALESCE(inv.oversell_limit, 0) ELSE 0 END)
                 END AS cap
        ) derived
        -- Unlimited has no catalogue ceiling to exceed. Its historical seats
        -- are real, but recording a capacity adjustment from 0 to N would turn
        -- an uncapped ticket into a finite, full one in the operator's audit.
        WHERE NOT c.is_unlimited AND c.capacity > derived.cap;
        """
    )

    # Existing waitlisted registrations become queue entries, ordered by when
    # they registered. Their seats default to 1: the pre-existing schema has no
    # per-registration seat count, and inventing a larger party from nothing
    # would let one backfilled row block a queue.
    op.execute(
        """
        INSERT INTO activity_waitlist_positions
          (activity_id, ticket_type_id, registration_id, user_id, seats, priority, status, joined_at)
        SELECT r.activity_id, r.ticket_type_id, r.id, r.user_id, 1, 0, 'waiting',
               COALESCE(r.created_at, now())
        FROM activity_registrations r
        WHERE r.status = 'waitlisted' AND r.ticket_type_id IS NOT NULL
        ON CONFLICT (registration_id) DO NOTHING;
        """
    )

    # Give historical registrations the same ownership record and event state
    # as registrations created after this migration. Without these rows, a
    # later cancellation could not tell whether to release a held or confirmed
    # seat, leaving the counter permanently occupied.
    _run(
        """
        INSERT INTO activity_capacity_reservations
          (idempotency_key, activity_id, ticket_type_id, registration_id, user_id,
           seats, outcome, waitlist_entry_id)
        SELECT 'migration:20260812_0106:' || r.id::text,
               r.activity_id, r.ticket_type_id, r.id, r.user_id, 1,
               CASE WHEN r.status = 'waitlisted' THEN 'waitlist' ELSE 'fits' END,
               p.id
        FROM activity_registrations r
        LEFT JOIN activity_waitlist_positions p ON p.registration_id = r.id
        WHERE r.ticket_type_id IS NOT NULL
          AND r.status IN ('confirmed','pending_approval','approved_pending_payment',
                           'pending_payment','payment_processing','waitlisted')
        ON CONFLICT (idempotency_key) DO NOTHING;

        INSERT INTO activity_capacity_events
          (activity_id, ticket_type_id, registration_id, event_type, seats, reason, metadata)
        SELECT r.activity_id, r.ticket_type_id, r.id,
               CASE WHEN r.status = 'confirmed' THEN 'seat_confirmed' ELSE 'seat_held' END,
               1, 'backfill: historical registration state',
               jsonb_build_object('migration', '20260812_0106', 'status', r.status)
        FROM activity_registrations r
        WHERE r.ticket_type_id IS NOT NULL
          AND r.status IN ('confirmed','pending_approval','approved_pending_payment',
                           'pending_payment','payment_processing');
        """
    )


def downgrade() -> None:
    _run(
        """
        DROP TABLE IF EXISTS activity_capacity_events;
        DROP TABLE IF EXISTS activity_waitlist_promotion_offers;
        DROP TABLE IF EXISTS activity_waitlist_positions;
        DROP TABLE IF EXISTS activity_capacity_reservations;
        DROP TABLE IF EXISTS activity_capacity_counters;
        """
    )
