"""Permission catalog — the single source of truth for authorisation codes.

The database stores grants (role -> permission code); this module defines which
codes exist, how they are grouped in the UI, and the default system roles.
"""

from __future__ import annotations

from enum import StrEnum


class P(StrEnum):
    # Hotel configuration
    HOTEL_VIEW = "hotel.view"
    CONFIG_HOTEL = "config.hotel.manage"
    CONFIG_ROOMS = "config.rooms.manage"
    CONFIG_FACILITIES = "config.facilities.manage"
    CONFIG_TAXES = "config.taxes.manage"
    CONFIG_CURRENCIES = "config.currencies.manage"
    # Rooms
    ROOMS_VIEW = "rooms.view"
    ROOMS_BLOCK = "rooms.block"
    # Reservations
    RESERVATIONS_VIEW = "reservations.view"
    RESERVATIONS_CREATE = "reservations.create"
    RESERVATIONS_EDIT = "reservations.edit"
    RESERVATIONS_CANCEL = "reservations.cancel"
    RESERVATIONS_OVERBOOK = "reservations.overbook"
    RESERVATIONS_OVERRIDE = "reservations.override_restrictions"
    # Guests
    GUESTS_VIEW = "guests.view"
    GUESTS_EDIT = "guests.edit"
    GUESTS_VIEW_SENSITIVE = "guests.view_sensitive"
    GUESTS_EXPORT = "guests.export"
    GUESTS_MERGE = "guests.merge"
    # Front desk
    FRONTDESK_CHECKIN = "frontdesk.checkin"
    FRONTDESK_CHECKOUT = "frontdesk.checkout"
    # End-of-day closure (night audit)
    NIGHT_AUDIT = "nightaudit.run"
    # Guest folio
    FOLIO_POST = "folio.post"
    FOLIO_ADJUST = "folio.adjust"
    # Finance
    PAYMENTS_VIEW = "payments.view"
    PAYMENTS_RECORD = "payments.record"
    PAYMENTS_REFUND = "payments.refund"
    PAYMENTS_VOID = "payments.void"
    INVOICES_VIEW = "invoices.view"
    INVOICES_ISSUE = "invoices.issue"
    INVOICES_VOID = "invoices.void"
    # Restaurant & bar
    RESTAURANT_VIEW = "restaurant.view"
    RESTAURANT_ORDER = "restaurant.order"
    RESTAURANT_KITCHEN = "restaurant.kitchen"
    RESTAURANT_SETTLE = "restaurant.settle"
    RESTAURANT_VOID = "restaurant.void"
    RESTAURANT_MANAGE = "restaurant.manage"
    # Vehicle rental
    VEHICLES_VIEW = "vehicles.view"
    VEHICLES_RENT = "vehicles.rent"
    VEHICLES_MANAGE = "vehicles.manage"
    # Pricing
    PRICING_VIEW = "pricing.view"
    PRICING_MANAGE = "pricing.manage"
    # Housekeeping & maintenance
    HOUSEKEEPING_VIEW = "housekeeping.view"
    HOUSEKEEPING_UPDATE = "housekeeping.update"
    HOUSEKEEPING_ASSIGN = "housekeeping.assign"
    MAINTENANCE_VIEW = "maintenance.view"
    MAINTENANCE_REPORT = "maintenance.report"
    MAINTENANCE_MANAGE = "maintenance.manage"
    # Reporting
    REPORTS_VIEW = "reports.view"
    REPORTS_FINANCIAL = "reports.financial"
    # Channel manager
    CHANNELS_VIEW = "channels.view"
    CHANNELS_MANAGE = "channels.manage"
    # Administration
    USERS_VIEW = "users.view"
    USERS_MANAGE = "users.manage"
    ROLES_MANAGE = "roles.manage"
    SESSIONS_MANAGE = "sessions.manage"
    AUDIT_VIEW = "audit.view"
    BACKUPS_MANAGE = "backups.manage"


ALL_PERMISSIONS: frozenset[str] = frozenset(p.value for p in P)

# UI grouping (group key is translated client-side as permissions.groups.<key>).
PERMISSION_GROUPS: dict[str, list[P]] = {
    "configuration": [
        P.HOTEL_VIEW,
        P.CONFIG_HOTEL,
        P.CONFIG_ROOMS,
        P.CONFIG_FACILITIES,
        P.CONFIG_TAXES,
        P.CONFIG_CURRENCIES,
    ],
    "rooms": [P.ROOMS_VIEW, P.ROOMS_BLOCK],
    "reservations": [
        P.RESERVATIONS_VIEW,
        P.RESERVATIONS_CREATE,
        P.RESERVATIONS_EDIT,
        P.RESERVATIONS_CANCEL,
        P.RESERVATIONS_OVERBOOK,
        P.RESERVATIONS_OVERRIDE,
    ],
    "guests": [P.GUESTS_VIEW, P.GUESTS_EDIT, P.GUESTS_VIEW_SENSITIVE, P.GUESTS_EXPORT, P.GUESTS_MERGE],
    "frontdesk": [P.FRONTDESK_CHECKIN, P.FRONTDESK_CHECKOUT, P.NIGHT_AUDIT],
    "folio": [P.FOLIO_POST, P.FOLIO_ADJUST],
    "payments": [P.PAYMENTS_VIEW, P.PAYMENTS_RECORD, P.PAYMENTS_REFUND, P.PAYMENTS_VOID],
    "invoices": [P.INVOICES_VIEW, P.INVOICES_ISSUE, P.INVOICES_VOID],
    "restaurant": [
        P.RESTAURANT_VIEW,
        P.RESTAURANT_ORDER,
        P.RESTAURANT_KITCHEN,
        P.RESTAURANT_SETTLE,
        P.RESTAURANT_VOID,
        P.RESTAURANT_MANAGE,
    ],
    "vehicles": [P.VEHICLES_VIEW, P.VEHICLES_RENT, P.VEHICLES_MANAGE],
    "pricing": [P.PRICING_VIEW, P.PRICING_MANAGE],
    "housekeeping": [P.HOUSEKEEPING_VIEW, P.HOUSEKEEPING_UPDATE, P.HOUSEKEEPING_ASSIGN],
    "maintenance": [P.MAINTENANCE_VIEW, P.MAINTENANCE_REPORT, P.MAINTENANCE_MANAGE],
    "reports": [P.REPORTS_VIEW, P.REPORTS_FINANCIAL],
    "channels": [P.CHANNELS_VIEW, P.CHANNELS_MANAGE],
    "administration": [
        P.USERS_VIEW,
        P.USERS_MANAGE,
        P.ROLES_MANAGE,
        P.SESSIONS_MANAGE,
        P.AUDIT_VIEW,
        P.BACKUPS_MANAGE,
    ],
}
assert {p for ps in PERMISSION_GROUPS.values() for p in ps} == set(P), "ungrouped permission"

_OPS_VIEW = {P.HOTEL_VIEW, P.ROOMS_VIEW}
_FRONT = {
    P.RESERVATIONS_VIEW,
    P.RESERVATIONS_CREATE,
    P.RESERVATIONS_EDIT,
    P.RESERVATIONS_CANCEL,
    P.GUESTS_VIEW,
    P.GUESTS_EDIT,
    P.FRONTDESK_CHECKIN,
    P.FRONTDESK_CHECKOUT,
    P.FOLIO_POST,
    P.PAYMENTS_VIEW,
    P.PAYMENTS_RECORD,
    P.INVOICES_VIEW,
    P.INVOICES_ISSUE,
    P.PRICING_VIEW,
    P.HOUSEKEEPING_VIEW,
    P.MAINTENANCE_VIEW,
    P.MAINTENANCE_REPORT,
    P.VEHICLES_VIEW,
    P.VEHICLES_RENT,
}

# code -> permissions. Names/descriptions are translated client-side (roles.system.<code>).
SYSTEM_ROLES: dict[str, set[P]] = {
    "super_admin": set(P),
    "hotel_admin": set(P) - {P.BACKUPS_MANAGE},
    "manager": set(P) - {P.ROLES_MANAGE, P.BACKUPS_MANAGE, P.USERS_MANAGE},
    # Night shift receptionists usually run the end-of-day closure.
    "receptionist": _OPS_VIEW | _FRONT | {P.ROOMS_BLOCK, P.NIGHT_AUDIT},
    "reservation_manager": _OPS_VIEW
    | {
        P.RESERVATIONS_VIEW,
        P.RESERVATIONS_CREATE,
        P.RESERVATIONS_EDIT,
        P.RESERVATIONS_CANCEL,
        P.RESERVATIONS_OVERBOOK,
        P.RESERVATIONS_OVERRIDE,
        P.GUESTS_VIEW,
        P.GUESTS_EDIT,
        P.GUESTS_MERGE,
        P.PRICING_VIEW,
        P.PRICING_MANAGE,
        P.CHANNELS_VIEW,
        P.REPORTS_VIEW,
        P.PAYMENTS_VIEW,
    },
    "housekeeping": _OPS_VIEW
    | {P.HOUSEKEEPING_VIEW, P.HOUSEKEEPING_UPDATE, P.MAINTENANCE_VIEW, P.MAINTENANCE_REPORT},
    "housekeeping_supervisor": _OPS_VIEW
    | {
        P.HOUSEKEEPING_VIEW,
        P.HOUSEKEEPING_UPDATE,
        P.HOUSEKEEPING_ASSIGN,
        P.MAINTENANCE_VIEW,
        P.MAINTENANCE_REPORT,
        P.RESERVATIONS_VIEW,
    },
    "accountant": _OPS_VIEW
    | {
        P.RESERVATIONS_VIEW,
        P.GUESTS_VIEW,
        P.FOLIO_POST,
        P.FOLIO_ADJUST,
        P.PAYMENTS_VIEW,
        P.PAYMENTS_RECORD,
        P.PAYMENTS_REFUND,
        P.PAYMENTS_VOID,
        P.INVOICES_VIEW,
        P.INVOICES_ISSUE,
        P.INVOICES_VOID,
        P.REPORTS_VIEW,
        P.REPORTS_FINANCIAL,
        P.PRICING_VIEW,
        P.CONFIG_CURRENCIES,
    },
    "maintenance": _OPS_VIEW
    | {P.MAINTENANCE_VIEW, P.MAINTENANCE_REPORT, P.MAINTENANCE_MANAGE, P.HOUSEKEEPING_VIEW},
    "restaurant_manager": _OPS_VIEW
    | {
        P.RESTAURANT_VIEW,
        P.RESTAURANT_ORDER,
        P.RESTAURANT_KITCHEN,
        P.RESTAURANT_SETTLE,
        P.RESTAURANT_VOID,
        P.RESTAURANT_MANAGE,
        P.MAINTENANCE_VIEW,
        P.MAINTENANCE_REPORT,
    },
    "waiter": {P.HOTEL_VIEW, P.RESTAURANT_VIEW, P.RESTAURANT_ORDER, P.RESTAURANT_SETTLE},
    "kitchen": {P.HOTEL_VIEW, P.RESTAURANT_VIEW, P.RESTAURANT_KITCHEN, P.MAINTENANCE_REPORT},
}
