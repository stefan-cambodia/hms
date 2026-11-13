"""Imports every ORM model so metadata is complete (Alembic, tests)."""

from app.core.audit import AuditLog  # noqa: F401
from app.modules.auth.models import (  # noqa: F401
    LoginEvent,
    RecoveryCode,
    Role,
    RolePermission,
    User,
    UserHotelRole,
    UserSession,
)
from app.modules.billing.models import Currency, FolioCharge, Invoice, Payment  # noqa: F401
from app.modules.channels.models import (  # noqa: F401
    ChannelBooking,
    ChannelConnection,
    ChannelDirtyRange,
    ChannelInventoryState,
    ChannelMessage,
    ChannelRateMap,
    ChannelRateState,
    ChannelRoomMap,
    ChannelSyncStatus,
)
from app.modules.facilities.models import Facility, Service, TaxRate  # noqa: F401
from app.modules.guests.models import Guest  # noqa: F401
from app.modules.hotels.models import Building, Floor, Hotel, Organization  # noqa: F401
from app.modules.housekeeping.models import HousekeepingTask, RoomStatusChange  # noqa: F401
from app.modules.maintenance.models import MaintenanceRequest, MaintenanceUpdate  # noqa: F401
from app.modules.media.models import MediaFile  # noqa: F401
from app.modules.nightaudit.models import DayClosure  # noqa: F401
from app.modules.pricing.models import CancellationPolicy, DailyRate, PricingRule, RatePlan  # noqa: F401
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
from app.modules.restaurant.models import (  # noqa: F401
    BreakfastMark,
    DiningTable,
    MenuCategory,
    MenuItem,
    Order,
    OrderLine,
    OrderPayment,
    Outlet,
)
from app.modules.rooms.models import Amenity, Room, RoomType  # noqa: F401
from app.modules.vehicles.models import Rental, RentalPayment, Vehicle  # noqa: F401
