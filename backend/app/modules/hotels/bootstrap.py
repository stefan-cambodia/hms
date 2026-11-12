"""First-time installation and per-hotel default data."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.context import Actor
from app.core.errors import Conflict
from app.core.permissions import SYSTEM_ROLES
from app.core.security import hash_password
from app.modules.auth.models import Role, RolePermission, User, UserHotelRole
from app.modules.auth.service import check_password_policy
from app.modules.hotels.models import Hotel, Organization
from app.modules.rooms.models import Amenity

# Default in-room amenities, translated in all supported languages. Hotels can
# edit, deactivate, or add any number of custom amenities.
DEFAULT_AMENITIES: list[tuple[str, str, dict[str, str]]] = [
    (
        "air_conditioning",
        "snowflake",
        {
            "en": "Air conditioning",
            "fr": "Climatisation",
            "zh-CN": "空调",
            "ru": "Кондиционер",
            "km": "ម៉ាស៊ីនត្រជាក់",
        },
    ),
    (
        "tv",
        "device-tv",
        {"en": "Television", "fr": "Télévision", "zh-CN": "电视", "ru": "Телевизор", "km": "ទូរទស្សន៍"},
    ),
    (
        "refrigerator",
        "fridge",
        {"en": "Refrigerator", "fr": "Réfrigérateur", "zh-CN": "冰箱", "ru": "Холодильник", "km": "ទូទឹកកក"},
    ),
    (
        "safe",
        "lock",
        {"en": "Safe", "fr": "Coffre-fort", "zh-CN": "保险箱", "ru": "Сейф", "km": "ទូដែកសុវត្ថិភាព"},
    ),
    ("wifi", "wifi", {"en": "Wi-Fi", "fr": "Wi-Fi", "zh-CN": "无线网络", "ru": "Wi-Fi", "km": "វ៉ាយហ្វាយ"}),
    (
        "desk",
        "desk",
        {"en": "Desk", "fr": "Bureau", "zh-CN": "书桌", "ru": "Письменный стол", "km": "តុធ្វើការ"},
    ),
    (
        "balcony",
        "building-arch",
        {"en": "Balcony", "fr": "Balcon", "zh-CN": "阳台", "ru": "Балкон", "km": "រានហាល"},
    ),
    (
        "bathtub",
        "bath",
        {"en": "Bathtub", "fr": "Baignoire", "zh-CN": "浴缸", "ru": "Ванна", "km": "អាងងូតទឹក"},
    ),
    ("shower", "droplet", {"en": "Shower", "fr": "Douche", "zh-CN": "淋浴", "ru": "Душ", "km": "ផ្កាឈូក"}),
    (
        "hair_dryer",
        "wind",
        {"en": "Hair dryer", "fr": "Sèche-cheveux", "zh-CN": "吹风机", "ru": "Фен", "km": "ម៉ាស៊ីនសម្ងួតសក់"},
    ),
    (
        "coffee_machine",
        "coffee",
        {
            "en": "Coffee machine",
            "fr": "Machine à café",
            "zh-CN": "咖啡机",
            "ru": "Кофемашина",
            "km": "ម៉ាស៊ីនឆុងកាហ្វេ",
        },
    ),
    (
        "kitchen",
        "tools-kitchen-2",
        {"en": "Kitchen", "fr": "Cuisine", "zh-CN": "厨房", "ru": "Кухня", "km": "ផ្ទះបាយ"},
    ),
    (
        "sea_view",
        "ripple",
        {"en": "Sea view", "fr": "Vue sur la mer", "zh-CN": "海景", "ru": "Вид на море", "km": "ទេសភាពសមុទ្រ"},
    ),
    (
        "garden_view",
        "plant",
        {
            "en": "Garden view",
            "fr": "Vue sur le jardin",
            "zh-CN": "花园景观",
            "ru": "Вид на сад",
            "km": "ទេសភាពសួនច្បារ",
        },
    ),
]

SYSTEM_ROLE_NAMES = {
    "super_admin": "Super Administrator",
    "hotel_admin": "Hotel Administrator",
    "manager": "Manager",
    "receptionist": "Receptionist",
    "reservation_manager": "Reservation Manager",
    "housekeeping": "Housekeeping",
    "accountant": "Accountant",
    "maintenance": "Maintenance Staff",
}


async def sync_system_roles(db: AsyncSession, organization_id: uuid.UUID) -> dict[str, Role]:
    """Create or update the protected system roles so their permission sets
    always match the catalog (new permissions propagate on upgrade)."""
    existing = {
        r.code: r
        for r in await db.scalars(
            select(Role).where(Role.organization_id == organization_id, Role.is_system.is_(True))
        )
    }
    roles: dict[str, Role] = {}
    for code, perms in SYSTEM_ROLES.items():
        role = existing.get(code)
        if role is None:
            role = Role(
                organization_id=organization_id,
                code=code,
                name=SYSTEM_ROLE_NAMES[code],
                is_system=True,
                version=1,
            )
            db.add(role)
            await db.flush()
        await db.execute(delete(RolePermission).where(RolePermission.role_id == role.id))
        db.add_all(RolePermission(role_id=role.id, permission=p.value) for p in perms)
        roles[code] = role
    await db.flush()
    return roles


async def seed_hotel_defaults(db: AsyncSession, hotel: Hotel) -> None:
    present = set(await db.scalars(select(Amenity.code).where(Amenity.hotel_id == hotel.id)))
    for i, (code, icon, name) in enumerate(DEFAULT_AMENITIES):
        if code not in present:
            db.add(
                Amenity(
                    hotel_id=hotel.id,
                    code=code,
                    icon=icon,
                    name=name,
                    scope="room",
                    sort_order=i * 10,
                    version=1,
                )
            )
    await db.flush()


@dataclass
class BootstrapResult:
    organization: Organization
    hotel: Hotel
    admin: User


async def bootstrap(
    db: AsyncSession,
    *,
    organization_name: str,
    hotel_name: str,
    hotel_code: str,
    admin_email: str,
    admin_password: str,
    admin_name: str,
    timezone: str = "UTC",
    currency_code: str = "USD",
    default_language: str = "en",
) -> BootstrapResult:
    """Create the first organisation, hotel and super administrator.
    Refuses to run if any user already exists."""
    if await db.scalar(select(User.id).limit(1)) is not None:
        raise Conflict("ALREADY_INITIALIZED", "The system is already initialised")
    check_password_policy(admin_password, field="admin_password")

    org = Organization(name=organization_name)
    db.add(org)
    await db.flush()
    hotel = Hotel(
        organization_id=org.id,
        code=hotel_code,
        name=hotel_name,
        timezone=timezone,
        currency_code=currency_code,
        default_language=default_language,
        version=1,
    )
    db.add(hotel)
    await db.flush()
    roles = await sync_system_roles(db, org.id)
    admin = User(
        organization_id=org.id,
        email=admin_email,
        full_name=admin_name,
        password_hash=hash_password(admin_password),
        is_superadmin=True,
        preferred_language=default_language,
        version=1,
    )
    db.add(admin)
    await db.flush()
    db.add(UserHotelRole(user_id=admin.id, hotel_id=hotel.id, role_id=roles["super_admin"].id))
    await seed_hotel_defaults(db, hotel)
    actor = Actor(user_id=admin.id, organization_id=org.id, source="cli")
    audit.record(db, actor, "system.bootstrap", "organization", org.id, hotel_id=hotel.id)
    await db.commit()
    return BootstrapResult(organization=org, hotel=hotel, admin=admin)
