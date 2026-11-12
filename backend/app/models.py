"""Imports every ORM model so metadata is complete (Alembic, tests)."""

from app.core.audit import AuditLog  # noqa: F401
from app.modules.auth.models import (  # noqa: F401
    LoginEvent,
    Role,
    RolePermission,
    User,
    UserHotelRole,
    UserSession,
)
from app.modules.facilities.models import Facility, Service, TaxRate  # noqa: F401
from app.modules.guests.models import Guest  # noqa: F401
from app.modules.hotels.models import Building, Floor, Hotel, Organization  # noqa: F401
from app.modules.reservations.models import (  # noqa: F401
    DocumentSequence,
    IdempotencyKey,
    Reservation,
    ReservationEvent,
    ReservationNight,
    ReservationRoom,
    RoomAllocation,
    RoomBlock,
)
from app.modules.rooms.models import Amenity, Room, RoomType  # noqa: F401
