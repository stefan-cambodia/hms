"""room service history: the nights each room was part of the hotel

The reports counted only rooms in service today, so a room taken out of
service also disappeared from past periods. Each room now has periods
[first night, first night no longer counted), kept by a trigger on rooms:
created in service -> a period opens tonight; deactivated -> it closes
tonight; reactivated -> a new one opens (or the one closed the same day
reopens). The history of existing rooms is rebuilt from the audit trail.

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-14 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

IN_HOTELS = "hotel_id = ANY ((SELECT hms_hotels())::uuid[])"

TRIGGER_FUNCTION = """
CREATE FUNCTION hms_room_service_period() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  tonight date;
BEGIN
  -- The hotel's business date: a change made today applies from tonight.
  SELECT (now() AT TIME ZONE h.timezone)::date INTO tonight FROM hotels h WHERE h.id = NEW.hotel_id;
  IF TG_OP = 'INSERT' THEN
    IF NEW.is_active THEN
      INSERT INTO room_service_periods (id, hotel_id, room_id, period)
      VALUES (gen_random_uuid(), NEW.hotel_id, NEW.id, daterange(tonight, NULL));
    END IF;
  ELSIF NEW.is_active AND NOT OLD.is_active THEN
    -- Reactivated the day it was deactivated: one continuous period.
    UPDATE room_service_periods SET period = daterange(lower(period), NULL)
     WHERE room_id = NEW.id AND upper(period) = tonight;
    IF NOT FOUND THEN
      INSERT INTO room_service_periods (id, hotel_id, room_id, period)
      VALUES (gen_random_uuid(), NEW.hotel_id, NEW.id, daterange(tonight, NULL));
    END IF;
  ELSIF OLD.is_active AND NOT NEW.is_active THEN
    -- Opened tonight and closed tonight: the room never counted.
    DELETE FROM room_service_periods
     WHERE room_id = NEW.id AND upper_inf(period) AND lower(period) >= tonight;
    UPDATE room_service_periods SET period = daterange(lower(period), tonight)
     WHERE room_id = NEW.id AND upper_inf(period);
  END IF;
  RETURN NEW;
END $$
"""

# Existing rooms: in service from their creation; a room out of service today
# until the last time it was deactivated (audit trail), else its last update.
BACKFILL = """
WITH spans AS (
  SELECT r.id AS room_id, r.hotel_id, r.is_active,
         (r.created_at AT TIME ZONE h.timezone)::date AS first_night,
         coalesce(
           (SELECT (max(a.at) AT TIME ZONE h.timezone)::date FROM audit_logs a
             WHERE a.entity_type = 'room' AND a.entity_id = r.id::text
               AND a.changes -> 'is_active' ->> 1 = 'false'),
           (r.updated_at AT TIME ZONE h.timezone)::date
         ) AS out_from
  FROM rooms r JOIN hotels h ON h.id = r.hotel_id
)
INSERT INTO room_service_periods (id, hotel_id, room_id, period)
SELECT gen_random_uuid(), hotel_id, room_id,
       CASE WHEN is_active THEN daterange(first_night, NULL)
            ELSE daterange(first_night, greatest(out_from, first_night)) END
FROM spans
WHERE is_active OR out_from > first_night
"""


def upgrade() -> None:
    op.create_table(
        "room_service_periods",
        sa.Column("hotel_id", sa.UUID(), nullable=False),
        sa.Column("room_id", sa.UUID(), nullable=False),
        sa.Column("period", postgresql.DATERANGE(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.CheckConstraint("NOT isempty(period)", name=op.f("ck_room_service_periods_non_empty")),
        postgresql.ExcludeConstraint(
            (sa.column("room_id"), "="),
            (sa.column("period"), "&&"),
            using="gist",
            name="ex_room_service_periods_no_overlap",
        ),
        sa.ForeignKeyConstraint(
            ["hotel_id"],
            ["hotels.id"],
            name=op.f("fk_room_service_periods_hotel_id_hotels"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["room_id"], ["rooms.id"], name=op.f("fk_room_service_periods_room_id_rooms"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_room_service_periods")),
    )
    op.execute("ALTER TABLE room_service_periods ENABLE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant ON room_service_periods USING ({IN_HOTELS}) WITH CHECK ({IN_HOTELS})")
    op.execute(BACKFILL)
    op.execute(TRIGGER_FUNCTION)
    op.execute(
        "CREATE TRIGGER room_service_period AFTER INSERT OR UPDATE OF is_active ON rooms "
        "FOR EACH ROW EXECUTE FUNCTION hms_room_service_period()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS room_service_period ON rooms")
    op.execute("DROP FUNCTION IF EXISTS hms_room_service_period()")
    op.drop_table("room_service_periods")
