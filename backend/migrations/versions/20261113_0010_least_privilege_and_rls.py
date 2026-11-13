"""least-privilege application role and row-level security

The API no longer connects as the schema owner. It connects with a login role
that is a member of `hms_app`, which may read and write rows but not change
the schema, truncate tables, or update/delete append-only records. Every table
holding tenant data has row-level security: a transaction only sees the rows
of the organisation (and, for hotel requests, the hotel) it declared with
`set_config('hms.org_id' / 'hms.hotel_ids')` (app/core/tenancy.py). The few
lookups that must happen before the organisation is known are narrow
SECURITY DEFINER functions.

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-13 09:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "hms_app"

# Tables carrying hotel_id NOT NULL: visible only for the hotels in scope.
HOTEL_TABLES = (
    "amenities",
    "breakfast_marks",
    "buildings",
    "cancellation_policies",
    "channel_bookings",
    "channel_connections",
    "channel_messages",
    "channel_rate_maps",
    "channel_room_maps",
    "channel_sync_status",
    "currencies",
    "daily_rates",
    "document_sequences",
    "facilities",
    "floors",
    "folio_charges",
    "guests",
    "housekeeping_tasks",
    "idempotency_keys",
    "invoices",
    "maintenance_requests",
    "maintenance_updates",
    "menu_categories",
    "menu_items",
    "payments",
    "pricing_rules",
    "rate_plans",
    "reservation_events",
    "reservation_nights",
    "reservation_rooms",
    "reservations",
    "restaurant_order_lines",
    "restaurant_orders",
    "restaurant_outlets",
    "restaurant_payments",
    "restaurant_tables",
    "room_allocations",
    "room_blocks",
    "room_status_changes",
    "room_types",
    "rooms",
    "services",
    "tax_rates",
    "user_hotel_roles",
    "vehicle_rental_payments",
    "vehicle_rentals",
    "vehicles",
)
# Tables carrying organization_id NOT NULL.
ORG_TABLES = ("users", "roles")
# Tables without a tenant column: visible when their parent row is visible
# (the parent's own policy applies inside the EXISTS).
CHILD_TABLES = (
    ("user_sessions", "users", "user_id"),
    ("role_permissions", "roles", "role_id"),
    ("room_amenities", "rooms", "room_id"),
    ("room_type_amenities", "room_types", "room_type_id"),
    ("channel_dirty_ranges", "channel_connections", "connection_id"),
    ("channel_inventory_state", "channel_connections", "connection_id"),
    ("channel_rate_state", "channel_connections", "connection_id"),
)
# Append-only records: the application role may never delete them (and, for
# the logs, never change them). Triggers already refuse; this is a second lock.
NO_UPDATE = ("audit_logs", "login_events")
NO_DELETE = (
    "audit_logs",
    "login_events",
    "folio_charges",
    "payments",
    "invoices",
    "restaurant_payments",
    "vehicle_rental_payments",
)
DEFINER_FUNCTIONS = (
    "hms_login_org(text)",
    "hms_session_org(text)",
    "hms_installation_initialized()",
    "hms_single_organization()",
    "hms_channel_connections(uuid)",
)

IN_HOTELS = "hotel_id = ANY ((SELECT hms_hotels())::uuid[])"

FUNCTIONS = (
    """
    CREATE FUNCTION hms_org() RETURNS uuid LANGUAGE sql STABLE PARALLEL SAFE AS $$
      SELECT nullif(current_setting('hms.org_id', true), '')::uuid $$
    """,
    """
    CREATE FUNCTION hms_hotel_scope() RETURNS uuid[] LANGUAGE sql STABLE PARALLEL SAFE AS $$
      SELECT CASE WHEN coalesce(current_setting('hms.hotel_ids', true), '') = '' THEN NULL
                  ELSE string_to_array(current_setting('hms.hotel_ids', true), ',')::uuid[] END $$
    """,
    """
    -- Hotels visible to the current transaction: those of the organisation,
    -- narrowed to the hotel scope when one is set. A hotel of another
    -- organisation named in the scope is never included.
    CREATE FUNCTION hms_hotels() RETURNS uuid[] LANGUAGE sql STABLE AS $$
      SELECT ARRAY(
        SELECT h.id FROM hotels h
        WHERE h.organization_id = hms_org()
          AND (hms_hotel_scope() IS NULL OR h.id = ANY (hms_hotel_scope()))
      ) $$
    """,
    """
    CREATE FUNCTION hms_login_org(p_email text) RETURNS uuid
      LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
      SELECT organization_id FROM users WHERE email = p_email $$
    """,
    """
    CREATE FUNCTION hms_session_org(p_token_hash text) RETURNS uuid
      LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
      SELECT u.organization_id FROM user_sessions s JOIN users u ON u.id = s.user_id
      WHERE s.token_hash = p_token_hash $$
    """,
    """
    CREATE FUNCTION hms_installation_initialized() RETURNS boolean
      LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
      SELECT EXISTS (SELECT 1 FROM users) $$
    """,
    """
    CREATE FUNCTION hms_single_organization() RETURNS boolean
      LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
      SELECT (SELECT count(*) FROM organizations) = 1 $$
    """,
    """
    -- Channel worker: which connections exist and which tenant owns them.
    CREATE FUNCTION hms_channel_connections(p_id uuid DEFAULT NULL)
      RETURNS TABLE (id uuid, hotel_id uuid, organization_id uuid, enabled boolean)
      LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
      SELECT c.id, c.hotel_id, h.organization_id, c.enabled
      FROM channel_connections c JOIN hotels h ON h.id = c.hotel_id
      WHERE p_id IS NULL OR c.id = p_id
      ORDER BY c.created_at, c.id $$
    """,
)


# SQL below is built from the constants of this file only (table, column and
# role names), never from input: `noqa: S608` marks those statements.


def upgrade() -> None:
    op.execute(
        """
        DO $$ BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hms_app') THEN
            CREATE ROLE hms_app NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
          END IF;
        END $$;
        """
    )

    # --- Tenant context (set per transaction by app/core/tenancy.py) and narrow
    # cross-tenant lookups (SECURITY DEFINER: run as the owner, bypassing RLS).
    for statement in FUNCTIONS:
        op.execute(statement)
    for fn in DEFINER_FUNCTIONS:
        op.execute(f"REVOKE ALL ON FUNCTION {fn} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {fn} TO {APP_ROLE}")

    # --- Row-level security -------------------------------------------------
    for table in HOTEL_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant ON {table} USING ({IN_HOTELS}) WITH CHECK ({IN_HOTELS})")
    for table in ORG_TABLES:
        cond = "organization_id = (SELECT hms_org())"
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant ON {table} USING ({cond}) WITH CHECK ({cond})")
    for table, parent, column in CHILD_TABLES:
        cond = f"EXISTS (SELECT 1 FROM {parent} p WHERE p.id = {table}.{column})"  # noqa: S608
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant ON {table} USING ({cond}) WITH CHECK ({cond})")

    op.execute("ALTER TABLE organizations ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant ON organizations USING (id = (SELECT hms_org())) "
        "WITH CHECK (id = (SELECT hms_org()))"
    )
    hotel_cond = (
        "organization_id = (SELECT hms_org()) AND "
        "((SELECT hms_hotel_scope()) IS NULL OR id = ANY ((SELECT hms_hotel_scope())::uuid[]))"
    )
    op.execute("ALTER TABLE hotels ENABLE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant ON hotels USING ({hotel_cond}) WITH CHECK ({hotel_cond})")

    audit_cond = f"organization_id = (SELECT hms_org()) AND (hotel_id IS NULL OR {IN_HOTELS})"
    op.execute("ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_read ON audit_logs FOR SELECT USING ({audit_cond})")
    op.execute(f"CREATE POLICY tenant_write ON audit_logs FOR INSERT WITH CHECK ({audit_cond})")

    # Login attempts: those of the organisation's users; attempts against
    # unknown e-mail addresses belong to no organisation and are only shown
    # when the installation has a single one. Anyone may record an attempt.
    user_visible = "EXISTS (SELECT 1 FROM users u WHERE u.id = login_events.user_id)"
    op.execute("ALTER TABLE login_events ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_read ON login_events FOR SELECT USING ("
        f"{user_visible} OR (user_id IS NULL AND (SELECT hms_org()) IS NOT NULL "
        "AND (SELECT hms_single_organization())))"
    )
    op.execute(
        f"CREATE POLICY tenant_write ON login_events FOR INSERT WITH CHECK (user_id IS NULL OR {user_visible})"
    )

    # --- Privileges of the application role --------------------------------
    op.execute(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {APP_ROLE}")
    op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE}")
    op.execute(f"REVOKE INSERT, UPDATE, DELETE ON alembic_version FROM {APP_ROLE}")
    op.execute(f"REVOKE UPDATE ON {', '.join(NO_UPDATE)} FROM {APP_ROLE}")
    op.execute(f"REVOKE DELETE ON {', '.join(NO_DELETE)} FROM {APP_ROLE}")
    # Tables added by later migrations get the same grants (row-level
    # security must still be enabled explicitly; a test checks every table).
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {APP_ROLE}"
    )
    op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE USAGE, SELECT ON SEQUENCES FROM {APP_ROLE}")  # noqa: S608
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM {APP_ROLE}"
    )
    op.execute(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {APP_ROLE}")
    op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {APP_ROLE}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {APP_ROLE}")
    tables = (
        list(HOTEL_TABLES)
        + list(ORG_TABLES)
        + [t for t, _, _ in CHILD_TABLES]
        + ["organizations", "hotels", "audit_logs", "login_events"]
    )
    for table in tables:
        for policy in ("tenant", "tenant_read", "tenant_write"):
            op.execute(f"DROP POLICY IF EXISTS {policy} ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    for fn in DEFINER_FUNCTIONS:
        op.execute(f"DROP FUNCTION IF EXISTS {fn}")
    op.execute("DROP FUNCTION IF EXISTS hms_hotels()")
    op.execute("DROP FUNCTION IF EXISTS hms_hotel_scope()")
    op.execute("DROP FUNCTION IF EXISTS hms_org()")
    # The role is cluster-wide (other databases may use it): it is kept.
