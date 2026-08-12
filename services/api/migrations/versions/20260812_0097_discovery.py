# ruff: noqa: E501

"""City preference, IP hints, venue locations, map providers and event sharing.

Covers GEO-001, MAP-001 and SHARE-001.

Revision ID: 20260812_0097
Revises: 20260812_0096
"""

from alembic import op

revision = "20260812_0097"
down_revision = "20260812_0096"
branch_labels = None
depends_on = None


def _run(script: str) -> None:
    for statement in script.split(";"):
        if statement.strip():
            op.execute(statement)


def upgrade() -> None:
    _run(
        """
        -- GEO-001. Only a manually confirmed city is stored. An IP-derived city
        -- never reaches this table, which is why confirmed_at is required
        -- whenever city_code is present.
        CREATE TABLE member_city_preferences (
          user_id UUID PRIMARY KEY REFERENCES users(id),
          city_code VARCHAR(32),
          allow_ip_suggestion BOOLEAN NOT NULL DEFAULT true,
          confirmed_at TIMESTAMPTZ,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CHECK (city_code IS NULL OR confirmed_at IS NOT NULL)
        );

        -- GEO-001. The only permitted record of an IP-derived location: a
        -- coarse city code plus a salted, truncated marker. There is no column
        -- that could hold an address or a coordinate, so the rule is enforced
        -- by the schema and not only by the code.
        CREATE TABLE discovery_ip_hints (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          user_id UUID REFERENCES users(id),
          city_code VARCHAR(32),
          ip_marker VARCHAR(32),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CHECK (ip_marker IS NULL OR length(ip_marker) <= 32)
        );
        CREATE INDEX discovery_ip_hints_marker_idx
          ON discovery_ip_hints (ip_marker, created_at DESC);

        -- MAP-001. manual_address is NOT NULL and separate from
        -- formatted_address: a geocoding failure can null the provider columns
        -- but can never blank what the operator typed.
        CREATE TABLE activity_venue_locations (
          activity_id UUID PRIMARY KEY REFERENCES activities(id),
          manual_address TEXT NOT NULL,
          formatted_address TEXT,
          country_code VARCHAR(2),
          region_code VARCHAR(32),
          city_code VARCHAR(32),
          latitude NUMERIC(9,6),
          longitude NUMERIC(9,6),
          provider VARCHAR(32),
          provider_place_ref VARCHAR(255),
          geocode_status VARCHAR(16) NOT NULL DEFAULT 'skipped',
          failure_code VARCHAR(64),
          geocoded_at TIMESTAMPTZ,
          updated_by UUID REFERENCES users(id),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CHECK (length(btrim(manual_address)) > 0),
          CHECK (geocode_status IN ('resolved','failed','skipped')),
          CHECK (provider IS NULL OR provider IN ('amap','google_maps')),
          CHECK (geocode_status <> 'resolved' OR (formatted_address IS NOT NULL AND provider IS NOT NULL)),
          CHECK (latitude IS NULL OR (latitude >= -90 AND latitude <= 90)),
          CHECK (longitude IS NULL OR (longitude >= -180 AND longitude <= 180))
        );
        CREATE INDEX activity_venue_locations_city_idx
          ON activity_venue_locations (city_code);

        -- MAP-001. Provider choice only. API keys stay in server-side settings
        -- so this table can be read by an operator without exposing a secret.
        CREATE TABLE map_provider_configs (
          country_code VARCHAR(2) PRIMARY KEY,
          provider VARCHAR(32) NOT NULL,
          is_active BOOLEAN NOT NULL DEFAULT true,
          updated_by UUID REFERENCES users(id),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CHECK (provider IN ('amap','google_maps'))
        );

        -- SHARE-001. The card payload is deterministic for a given
        -- (activity, card_version), so the fingerprint is stable and the row is
        -- safe to upsert.
        CREATE TABLE activity_share_cards (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          activity_id UUID NOT NULL REFERENCES activities(id),
          card_version INTEGER NOT NULL DEFAULT 1,
          fingerprint VARCHAR(64) NOT NULL,
          payload JSONB NOT NULL,
          cover_is_fallback BOOLEAN NOT NULL DEFAULT false,
          created_by UUID REFERENCES users(id),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (activity_id, card_version),
          CHECK (card_version >= 1),
          CHECK (length(fingerprint) = 64)
        );

        -- SHARE-001. canonical_url must be the authorized /events/ URL: the QR
        -- and the short link both resolve there, so access control lives in one
        -- place. Links are revoked, never deleted.
        CREATE TABLE activity_share_links (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          activity_id UUID NOT NULL REFERENCES activities(id),
          share_version INTEGER NOT NULL DEFAULT 1,
          short_code VARCHAR(32) NOT NULL,
          signature VARCHAR(64) NOT NULL,
          canonical_url TEXT NOT NULL,
          expires_at TIMESTAMPTZ,
          revoked_at TIMESTAMPTZ,
          revoked_reason TEXT,
          created_by UUID REFERENCES users(id),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (short_code),
          CHECK (share_version >= 1),
          CHECK (canonical_url LIKE 'https://%'),
          CHECK (position('/events/' in canonical_url) > 0),
          CHECK (revoked_at IS NULL OR revoked_reason IS NOT NULL)
        );
        CREATE INDEX activity_share_links_activity_idx
          ON activity_share_links (activity_id, share_version);

        CREATE TABLE activity_share_resolutions (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          activity_id UUID NOT NULL REFERENCES activities(id),
          short_code VARCHAR(32) NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX activity_share_resolutions_activity_idx
          ON activity_share_resolutions (activity_id, created_at DESC);

        CREATE TABLE discovery_audits (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          subject_type VARCHAR(64) NOT NULL,
          subject_id UUID,
          actor_id UUID REFERENCES users(id),
          actor_kind VARCHAR(16) NOT NULL,
          action VARCHAR(128) NOT NULL,
          reason TEXT,
          metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CHECK (actor_kind IN ('member','admin','system'))
        );
        CREATE INDEX discovery_audits_subject_idx
          ON discovery_audits (subject_type, subject_id, created_at DESC);
        """
    )

    # Existing activities keep whatever address the activities table already
    # holds. Backfilling a geocode here would call a third-party API from inside
    # a migration; the venue rows are created as 'skipped' instead, and an
    # operator (or a background job) geocodes them afterwards. The manually
    # entered address is never lost either way (MAP-001).
    op.execute(
        """
        INSERT INTO activity_venue_locations (activity_id, manual_address, geocode_status)
        SELECT a.id,
               COALESCE(NULLIF(btrim(loc.address_display_text), ''),
                        NULLIF(btrim(loc.venue_display_name), ''), '-'),
               'skipped'
        FROM activities a
        JOIN activity_localizations loc
          ON loc.activity_id = a.id AND loc.locale = a.default_locale
        WHERE COALESCE(loc.address_display_text, loc.venue_display_name) IS NOT NULL
        ON CONFLICT (activity_id) DO NOTHING;
        """
    )


def downgrade() -> None:
    _run(
        """
        DROP TABLE IF EXISTS discovery_audits;
        DROP TABLE IF EXISTS activity_share_resolutions;
        DROP TABLE IF EXISTS activity_share_links;
        DROP TABLE IF EXISTS activity_share_cards;
        DROP TABLE IF EXISTS map_provider_configs;
        DROP TABLE IF EXISTS activity_venue_locations;
        DROP TABLE IF EXISTS discovery_ip_hints;
        DROP TABLE IF EXISTS member_city_preferences;
        """
    )
