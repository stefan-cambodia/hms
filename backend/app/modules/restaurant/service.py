"""Restaurant & bar point of sale.

Check money (one computation, `recompute`):
    subtotal       = sum of non-void lines
    discount       = percent of the subtotal, or a fixed amount (≤ subtotal)
    service charge = outlet % of (subtotal − discount)
    taxes          = food & beverage taxes (percent; inclusive or exclusive)
                     on (subtotal − discount + service charge)
    total          = subtotal − discount + service charge + exclusive taxes
    balance        = total − payments (non-void, hotel currency)

Line workflow: new → (send) sent → preparing → ready → served; drinks and
items without a station go straight to served when sent. A sent line can only
be voided (with a reason, restaurant.void). The check closes itself when it is
fully paid; voiding a payment reopens it.

Room charge: the whole check is posted to the in-house guest's folio as an
"outlet" charge carrying the check's tax lines, in the same transaction.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit, crud, events, sequences
from app.core.context import HotelContext
from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed, field_error, register_constraint
from app.core.money import ZERO, round_money
from app.core.permissions import P
from app.modules.auth.models import User
from app.modules.billing import folio
from app.modules.billing import service as billing
from app.modules.billing.models import FolioCharge
from app.modules.facilities.models import Facility
from app.modules.guests.models import Guest
from app.modules.hotels.models import Hotel
from app.modules.pricing import service as pricing
from app.modules.pricing.models import RatePlan
from app.modules.reservations import idempotency
from app.modules.reservations.models import Reservation, ReservationRoom
from app.modules.restaurant.models import (
    BreakfastMark,
    DiningTable,
    MenuCategory,
    MenuItem,
    Order,
    OrderLine,
    OrderPayment,
    Outlet,
)
from app.modules.restaurant.schemas import LineOut
from app.modules.rooms.models import Room

register_constraint("uq_restaurant_orders_open_table", "TABLE_OCCUPIED")
register_constraint("uq_restaurant_outlets_hotel_id_code", "OUTLET_CODE_EXISTS", field="code")
register_constraint("uq_restaurant_tables_outlet_id_label", "TABLE_LABEL_EXISTS", field="label")
register_constraint("fk_menu_items_hotel_id_menu_categories", "CATEGORY_IN_USE")
register_constraint("fk_restaurant_orders_hotel_id_restaurant_outlets", "OUTLET_IN_USE")
register_constraint("fk_restaurant_orders_hotel_id_restaurant_tables", "TABLE_IN_USE")

BREAKFAST_PLANS = ("breakfast", "half_board", "full_board", "all_inclusive")
KITCHEN_FLOW = {
    "preparing": {"sent"},
    "ready": {"sent", "preparing"},
    "served": {"sent", "preparing", "ready"},
}


async def _hotel(db: AsyncSession, hotel_id: uuid.UUID) -> Hotel:
    hotel = await db.get(Hotel, hotel_id)
    assert hotel is not None
    return hotel


def _require(ctx: HotelContext, permission: P) -> None:
    if not ctx.has(permission):
        raise Forbidden("PERMISSION_DENIED", params={"permission": permission})


# --- configuration -----------------------------------------------------------------------

OUTLET_FIELDS = ("code", "name", "kind", "facility_id", "service_charge_percent", "sort_order", "is_active")
CATEGORY_FIELDS = ("outlet_id", "name", "sort_order", "is_active")
ITEM_FIELDS = (
    "outlet_id",
    "category_id",
    "code",
    "name",
    "description",
    "price",
    "station",
    "is_available",
    "sort_order",
    "is_active",
)
TABLE_FIELDS = ("outlet_id", "label", "area", "seats", "sort_order", "is_active")


async def list_outlets(db: AsyncSession, hotel_id: uuid.UUID) -> list[Outlet]:
    return list(
        await db.scalars(
            select(Outlet).where(Outlet.hotel_id == hotel_id).order_by(Outlet.sort_order, Outlet.code)
        )
    )


async def _outlet(db: AsyncSession, hotel_id: uuid.UUID, outlet_id: uuid.UUID) -> Outlet:
    return await crud.get_scoped(db, Outlet, hotel_id, outlet_id, code="OUTLET_NOT_FOUND")


async def create_outlet(db: AsyncSession, ctx: HotelContext, data: Any) -> Outlet:
    if data.facility_id:
        await crud.get_scoped(db, Facility, ctx.hotel_id, data.facility_id, code="FACILITY_NOT_FOUND")
    obj = Outlet(hotel_id=ctx.hotel_id, version=1, **data.model_dump())
    return await crud.create(db, ctx, obj, entity="restaurant_outlet", fields=OUTLET_FIELDS)


async def update_outlet(db: AsyncSession, ctx: HotelContext, outlet_id: uuid.UUID, data: Any) -> Outlet:
    obj = await _outlet(db, ctx.hotel_id, outlet_id)
    changes = data.model_dump(exclude_unset=True, exclude={"version"})
    if changes.get("facility_id"):
        await crud.get_scoped(db, Facility, ctx.hotel_id, changes["facility_id"], code="FACILITY_NOT_FOUND")
    return await crud.update(
        db, ctx, obj, changes, version=data.version, entity="restaurant_outlet", fields=OUTLET_FIELDS
    )


async def delete_outlet(db: AsyncSession, ctx: HotelContext, outlet_id: uuid.UUID) -> None:
    obj = await _outlet(db, ctx.hotel_id, outlet_id)
    await crud.delete(db, ctx, obj, entity="restaurant_outlet", fields=OUTLET_FIELDS)


async def list_categories(
    db: AsyncSession, hotel_id: uuid.UUID, outlet_id: uuid.UUID | None
) -> list[MenuCategory]:
    stmt = select(MenuCategory).where(MenuCategory.hotel_id == hotel_id)
    if outlet_id:
        stmt = stmt.where(MenuCategory.outlet_id == outlet_id)
    return list(await db.scalars(stmt.order_by(MenuCategory.sort_order, MenuCategory.created_at)))


async def create_category(db: AsyncSession, ctx: HotelContext, data: Any) -> MenuCategory:
    await _outlet(db, ctx.hotel_id, data.outlet_id)
    obj = MenuCategory(hotel_id=ctx.hotel_id, version=1, **data.model_dump())
    return await crud.create(db, ctx, obj, entity="menu_item", fields=CATEGORY_FIELDS)


async def update_category(
    db: AsyncSession, ctx: HotelContext, category_id: uuid.UUID, data: Any
) -> MenuCategory:
    obj = await crud.get_scoped(db, MenuCategory, ctx.hotel_id, category_id, code="CATEGORY_NOT_FOUND")
    changes = data.model_dump(exclude_unset=True, exclude={"version"})
    return await crud.update(
        db, ctx, obj, changes, version=data.version, entity="menu_item", fields=CATEGORY_FIELDS
    )


async def delete_category(db: AsyncSession, ctx: HotelContext, category_id: uuid.UUID) -> None:
    obj = await crud.get_scoped(db, MenuCategory, ctx.hotel_id, category_id, code="CATEGORY_NOT_FOUND")
    await crud.delete(db, ctx, obj, entity="menu_item", fields=CATEGORY_FIELDS)


async def list_items(db: AsyncSession, hotel_id: uuid.UUID, outlet_id: uuid.UUID | None) -> list[MenuItem]:
    stmt = select(MenuItem).where(MenuItem.hotel_id == hotel_id)
    if outlet_id:
        stmt = stmt.where(MenuItem.outlet_id == outlet_id)
    return list(await db.scalars(stmt.order_by(MenuItem.sort_order, MenuItem.created_at)))


async def create_item(db: AsyncSession, ctx: HotelContext, data: Any) -> MenuItem:
    category = await crud.get_scoped(
        db, MenuCategory, ctx.hotel_id, data.category_id, code="CATEGORY_NOT_FOUND"
    )
    obj = MenuItem(hotel_id=ctx.hotel_id, outlet_id=category.outlet_id, version=1, **data.model_dump())
    return await crud.create(db, ctx, obj, entity="menu_item", fields=ITEM_FIELDS)


async def update_item(db: AsyncSession, ctx: HotelContext, item_id: uuid.UUID, data: Any) -> MenuItem:
    obj = await crud.get_scoped(db, MenuItem, ctx.hotel_id, item_id, code="MENU_ITEM_NOT_FOUND")
    changes = data.model_dump(exclude_unset=True, exclude={"version"})
    if changes.get("category_id"):
        category = await crud.get_scoped(
            db, MenuCategory, ctx.hotel_id, changes["category_id"], code="CATEGORY_NOT_FOUND"
        )
        if category.outlet_id != obj.outlet_id:
            raise ValidationFailed(
                "CATEGORY_OTHER_OUTLET", fields=[field_error("category_id", "CATEGORY_OTHER_OUTLET")]
            )
    return await crud.update(
        db, ctx, obj, changes, version=data.version, entity="menu_item", fields=ITEM_FIELDS
    )


async def set_availability(
    db: AsyncSession, ctx: HotelContext, item_id: uuid.UUID, available: bool
) -> MenuItem:
    """Mark an item sold out / back (kitchen or managers)."""
    if not (ctx.has(P.RESTAURANT_KITCHEN) or ctx.has(P.RESTAURANT_MANAGE)):
        raise Forbidden("PERMISSION_DENIED", params={"permission": P.RESTAURANT_KITCHEN})
    obj = await crud.get_scoped(db, MenuItem, ctx.hotel_id, item_id, code="MENU_ITEM_NOT_FOUND")
    return await crud.update(
        db, ctx, obj, {"is_available": available}, version=obj.version, entity="menu_item", fields=ITEM_FIELDS
    )


async def delete_item(db: AsyncSession, ctx: HotelContext, item_id: uuid.UUID) -> None:
    obj = await crud.get_scoped(db, MenuItem, ctx.hotel_id, item_id, code="MENU_ITEM_NOT_FOUND")
    await crud.delete(db, ctx, obj, entity="menu_item", fields=ITEM_FIELDS)


async def list_tables(
    db: AsyncSession, hotel_id: uuid.UUID, outlet_id: uuid.UUID | None
) -> list[DiningTable]:
    stmt = select(DiningTable).where(DiningTable.hotel_id == hotel_id)
    if outlet_id:
        stmt = stmt.where(DiningTable.outlet_id == outlet_id)
    return list(await db.scalars(stmt.order_by(DiningTable.sort_order, DiningTable.label)))


async def create_table(db: AsyncSession, ctx: HotelContext, data: Any) -> DiningTable:
    await _outlet(db, ctx.hotel_id, data.outlet_id)
    obj = DiningTable(hotel_id=ctx.hotel_id, version=1, **data.model_dump())
    return await crud.create(db, ctx, obj, entity="restaurant_outlet", fields=TABLE_FIELDS)


async def update_table(db: AsyncSession, ctx: HotelContext, table_id: uuid.UUID, data: Any) -> DiningTable:
    obj = await crud.get_scoped(db, DiningTable, ctx.hotel_id, table_id, code="TABLE_NOT_FOUND")
    changes = data.model_dump(exclude_unset=True, exclude={"version"})
    return await crud.update(
        db, ctx, obj, changes, version=data.version, entity="restaurant_outlet", fields=TABLE_FIELDS
    )


async def delete_table(db: AsyncSession, ctx: HotelContext, table_id: uuid.UUID) -> None:
    obj = await crud.get_scoped(db, DiningTable, ctx.hotel_id, table_id, code="TABLE_NOT_FOUND")
    await crud.delete(db, ctx, obj, entity="restaurant_outlet", fields=TABLE_FIELDS)


# --- check money ---------------------------------------------------------------------------


async def _lines(db: AsyncSession, order_id: uuid.UUID) -> list[OrderLine]:
    return list(
        await db.scalars(
            select(OrderLine).where(OrderLine.order_id == order_id).order_by(OrderLine.created_at)
        )
    )


async def _payments(db: AsyncSession, order_id: uuid.UUID) -> list[OrderPayment]:
    return list(
        await db.scalars(
            select(OrderPayment).where(OrderPayment.order_id == order_id).order_by(OrderPayment.received_at)
        )
    )


async def recompute(db: AsyncSession, order: Order) -> None:
    """Recompute and store every amount of a check from its lines and payments."""
    hotel = await _hotel(db, order.hotel_id)
    outlet = await db.get(Outlet, order.outlet_id)
    assert outlet is not None
    cur = hotel.currency_code
    lines = [ln for ln in await _lines(db, order.id) if ln.status != "void"]
    subtotal = sum((ln.amount for ln in lines), ZERO)
    discount = ZERO
    if order.discount_kind == "percent" and order.discount_value:
        discount = round_money(subtotal * order.discount_value / 100, cur)
    elif order.discount_kind == "amount" and order.discount_value:
        discount = min(order.discount_value, subtotal)
    base = subtotal - discount
    service = round_money(base * outlet.service_charge_percent / 100, cur)
    taxes = [
        t for t in await pricing.active_taxes(db, order.hotel_id, "food_beverage") if t.kind == "percent"
    ]
    lines_tax = folio.merge_tax_lines(
        folio.tax_line_dicts(pricing.compute_taxes(taxes, base + service, 0, 0, cur))
    )
    order.subtotal = subtotal
    order.discount_total = discount
    order.service_charge = service
    order.tax_breakdown = lines_tax
    order.tax_total = sum((Decimal(t["amount"]) for t in lines_tax if not t["is_inclusive"]), ZERO)
    order.total = base + service + order.tax_total
    order.paid_total = sum((p.amount_base for p in await _payments(db, order.id) if not p.is_void), ZERO)


async def _publish(db: AsyncSession, ctx: HotelContext, order: Order, action: str, changes: dict) -> None:
    audit.record(
        db,
        ctx.actor,
        f"restaurant_order.{action}",
        "restaurant_order",
        order.id,
        hotel_id=ctx.hotel_id,
        changes=changes,
    )
    await events.emit(
        db,
        hotel_id=ctx.hotel_id,
        entity="restaurant_order",
        action="created" if action == "open" else "updated",
        entity_id=order.id,
        version=order.version,
        actor=ctx.actor,
    )


async def get_order(
    db: AsyncSession, hotel_id: uuid.UUID, order_id: uuid.UUID, *, for_update: bool = False
) -> Order:
    return await crud.get_scoped(db, Order, hotel_id, order_id, code="ORDER_NOT_FOUND", for_update=for_update)


def _require_open(order: Order) -> None:
    if order.status != "open":
        raise Conflict("ORDER_CLOSED", params={"status": order.status})


async def _stay(
    db: AsyncSession, hotel_id: uuid.UUID, rr_id: uuid.UUID, *, in_house: bool
) -> ReservationRoom:
    rr = (
        await db.scalars(
            select(ReservationRoom).where(ReservationRoom.id == rr_id, ReservationRoom.hotel_id == hotel_id)
        )
    ).one_or_none()
    if rr is None:
        raise NotFound("RESERVATION_ROOM_NOT_FOUND")
    if in_house and (rr.checked_in_at is None or rr.checked_out_at is not None):
        raise Conflict("GUEST_NOT_IN_HOUSE")
    return rr


# --- orders --------------------------------------------------------------------------------


async def open_order(db: AsyncSession, ctx: HotelContext, data: Any) -> Order:
    outlet = await _outlet(db, ctx.hotel_id, data.outlet_id)
    if not outlet.is_active:
        raise ValidationFailed("OUTLET_INACTIVE")
    if data.table_id:
        table = await crud.get_scoped(db, DiningTable, ctx.hotel_id, data.table_id, code="TABLE_NOT_FOUND")
        if table.outlet_id != outlet.id or not table.is_active:
            raise ValidationFailed("TABLE_NOT_FOUND", fields=[field_error("table_id", "TABLE_NOT_FOUND")])
    if data.reservation_room_id:
        await _stay(db, ctx.hotel_id, data.reservation_room_id, in_house=True)
    hotel = await _hotel(db, ctx.hotel_id)
    order = Order(
        id=uuid.uuid4(),
        hotel_id=ctx.hotel_id,
        outlet_id=outlet.id,
        number=f"CHK-{await sequences.next_value(db, ctx.hotel_id, 'restaurant_order'):06d}",
        business_date=hotel.today(),
        table_id=data.table_id if data.order_type == "dine_in" else None,
        order_type=data.order_type,
        covers=data.covers,
        status="open",
        reservation_room_id=data.reservation_room_id,
        notes=data.notes,
        opened_by=ctx.actor.user_id,
        version=1,
    )
    db.add(order)
    await db.flush()  # one open check per table (partial unique index)
    await _publish(db, ctx, order, "open", {"number": [None, order.number]})
    await db.commit()
    return order


async def update_order(db: AsyncSession, ctx: HotelContext, order_id: uuid.UUID, data: Any) -> Order:
    order = await get_order(db, ctx.hotel_id, order_id, for_update=True)
    crud.check_version(order, data.version)
    _require_open(order)
    changes = data.model_dump(exclude_unset=True, exclude={"version"})
    if changes.get("table_id"):
        table = await crud.get_scoped(
            db, DiningTable, ctx.hotel_id, changes["table_id"], code="TABLE_NOT_FOUND"
        )
        if table.outlet_id != order.outlet_id:
            raise ValidationFailed("TABLE_NOT_FOUND", fields=[field_error("table_id", "TABLE_NOT_FOUND")])
    if changes.get("reservation_room_id"):
        await _stay(db, ctx.hotel_id, changes["reservation_room_id"], in_house=True)
    before = {k: getattr(order, k) for k in changes}
    for k, v in changes.items():
        setattr(order, k, v)
    await db.flush()
    await _publish(db, ctx, order, "update", audit.diff(before, {k: getattr(order, k) for k in changes}))
    await db.commit()
    return order


async def add_lines(
    db: AsyncSession, ctx: HotelContext, order_id: uuid.UUID, data: Any, idempotency_key: str | None
) -> Order:
    digest = idempotency.digest(f"lines:{order_id}", data.model_dump(mode="json"))
    if idempotency_key and await idempotency.claim(db, ctx, idempotency_key, digest):
        return await get_order(db, ctx.hotel_id, order_id)
    order = await get_order(db, ctx.hotel_id, order_id, for_update=True)
    _require_open(order)
    ids = {x.menu_item_id for x in data.items}
    items = {
        i.id: i
        for i in await db.scalars(
            select(MenuItem).where(MenuItem.hotel_id == ctx.hotel_id, MenuItem.id.in_(ids))
        )
    }
    pending = {(ln.menu_item_id, ln.notes): ln for ln in await _lines(db, order.id) if ln.status == "new"}
    for x in data.items:
        item = items.get(x.menu_item_id)
        if item is None or item.outlet_id != order.outlet_id:
            raise NotFound("MENU_ITEM_NOT_FOUND")
        if not item.is_active or not item.is_available:
            raise Conflict(
                "ITEM_UNAVAILABLE", params={"item": item.name.get("en") or next(iter(item.name.values()))}
            )
        same = pending.get((item.id, x.notes))
        if same is not None and same.quantity + x.quantity <= 99:
            # Tapping an item again before sending adds to the same line.
            same.quantity += x.quantity
            same.amount = same.unit_price * same.quantity
            continue
        db.add(
            OrderLine(
                id=uuid.uuid4(),
                hotel_id=ctx.hotel_id,
                order_id=order.id,
                menu_item_id=item.id,
                category_id=item.category_id,
                name=dict(item.name),
                station=item.station,
                unit_price=item.price,
                quantity=x.quantity,
                amount=item.price * x.quantity,
                notes=x.notes,
                status="new",
                created_by=ctx.actor.user_id,
            )
        )
    await db.flush()
    await recompute(db, order)
    order.updated_at = datetime.now(UTC)
    await db.flush()
    if idempotency_key:
        await idempotency.bind(db, ctx, idempotency_key, order.id)
    await _publish(db, ctx, order, "lines", {"lines": [None, len(data.items)]})
    await db.commit()
    return order


async def _line(db: AsyncSession, order: Order, line_id: uuid.UUID) -> OrderLine:
    line = (
        await db.scalars(select(OrderLine).where(OrderLine.id == line_id, OrderLine.order_id == order.id))
    ).one_or_none()
    if line is None:
        raise NotFound("ORDER_LINE_NOT_FOUND")
    return line


async def update_line(
    db: AsyncSession, ctx: HotelContext, order_id: uuid.UUID, line_id: uuid.UUID, data: Any
) -> Order:
    order = await get_order(db, ctx.hotel_id, order_id, for_update=True)
    _require_open(order)
    line = await _line(db, order, line_id)
    if line.status != "new":
        raise Conflict("LINE_ALREADY_SENT")
    changes = data.model_dump(exclude_unset=True)
    if "quantity" in changes and changes["quantity"]:
        line.quantity = changes["quantity"]
        line.amount = line.unit_price * line.quantity
    if "notes" in changes:
        line.notes = changes["notes"]
    await db.flush()
    await recompute(db, order)
    order.updated_at = datetime.now(UTC)
    await db.flush()
    await _publish(db, ctx, order, "lines", {"line": [None, str(line.id)]})
    await db.commit()
    return order


async def remove_line(db: AsyncSession, ctx: HotelContext, order_id: uuid.UUID, line_id: uuid.UUID) -> Order:
    """Remove a line that was not sent yet (nothing was prepared)."""
    order = await get_order(db, ctx.hotel_id, order_id, for_update=True)
    _require_open(order)
    line = await _line(db, order, line_id)
    if line.status != "new":
        raise Conflict("LINE_ALREADY_SENT")
    await db.delete(line)
    await db.flush()
    await recompute(db, order)
    order.updated_at = datetime.now(UTC)
    await db.flush()
    await _publish(db, ctx, order, "lines", {"removed": [None, str(line_id)]})
    await db.commit()
    return order


async def send(db: AsyncSession, ctx: HotelContext, order_id: uuid.UUID) -> Order:
    """Send new lines to the kitchen/bar (items without a station are served)."""
    order = await get_order(db, ctx.hotel_id, order_id, for_update=True)
    _require_open(order)
    now = datetime.now(UTC)
    new = [ln for ln in await _lines(db, order.id) if ln.status == "new"]
    if not new:
        raise Conflict("NOTHING_TO_SEND")
    for ln in new:
        ln.sent_at = now
        if ln.station == "none":
            ln.status, ln.served_at = "served", now
        else:
            ln.status = "sent"
    order.updated_at = now
    await db.flush()
    await _publish(db, ctx, order, "send", {"sent": [None, len(new)]})
    await db.commit()
    return order


async def set_line_status(
    db: AsyncSession, ctx: HotelContext, order_id: uuid.UUID, line_id: uuid.UUID, status: str
) -> Order:
    order = await get_order(db, ctx.hotel_id, order_id, for_update=True)
    line = await _line(db, order, line_id)
    if status in ("preparing", "ready"):
        _require(ctx, P.RESTAURANT_KITCHEN)
    elif not (ctx.has(P.RESTAURANT_ORDER) or ctx.has(P.RESTAURANT_KITCHEN)):
        raise Forbidden("PERMISSION_DENIED", params={"permission": P.RESTAURANT_ORDER})
    if line.status not in KITCHEN_FLOW[status]:
        raise Conflict("INVALID_LINE_TRANSITION", params={"from": line.status, "to": status})
    now = datetime.now(UTC)
    line.status = status
    if status == "ready":
        line.ready_at = now
    elif status == "served":
        line.served_at = now
        line.ready_at = line.ready_at or now
    order.updated_at = now
    await db.flush()
    await _publish(db, ctx, order, "kitchen", {"line": [None, status]})
    await db.commit()
    return order


async def serve_ready(db: AsyncSession, ctx: HotelContext, order_id: uuid.UUID) -> Order:
    order = await get_order(db, ctx.hotel_id, order_id, for_update=True)
    now = datetime.now(UTC)
    ready = [ln for ln in await _lines(db, order.id) if ln.status == "ready"]
    if not ready:
        raise Conflict("NOTHING_READY")
    for ln in ready:
        ln.status, ln.served_at = "served", now
    order.updated_at = now
    await db.flush()
    await _publish(db, ctx, order, "served", {"served": [None, len(ready)]})
    await db.commit()
    return order


async def void_line(
    db: AsyncSession, ctx: HotelContext, order_id: uuid.UUID, line_id: uuid.UUID, reason: str
) -> Order:
    """Void a line already sent to the kitchen (needs restaurant.void)."""
    _require(ctx, P.RESTAURANT_VOID)
    order = await get_order(db, ctx.hotel_id, order_id, for_update=True)
    _require_open(order)
    line = await _line(db, order, line_id)
    if line.status == "void":
        raise Conflict("ALREADY_VOID")
    if line.status == "new":
        raise Conflict("LINE_NOT_SENT")  # simply remove it
    line.status = "void"
    line.void_reason = reason
    line.voided_at = datetime.now(UTC)
    line.voided_by = ctx.actor.user_id
    await db.flush()
    await recompute(db, order)
    order.updated_at = datetime.now(UTC)
    await db.flush()
    await _publish(db, ctx, order, "void_line", {"line": [line.amount, "void"], "reason": [None, reason]})
    await db.commit()
    return order


async def set_discount(db: AsyncSession, ctx: HotelContext, order_id: uuid.UUID, data: Any) -> Order:
    _require(ctx, P.RESTAURANT_VOID)
    order = await get_order(db, ctx.hotel_id, order_id, for_update=True)
    _require_open(order)
    if data.kind == "amount" and data.value is not None and data.value > order.subtotal:
        raise ValidationFailed("DISCOUNT_TOO_LARGE", fields=[field_error("value", "DISCOUNT_TOO_LARGE")])
    order.discount_kind = data.kind
    order.discount_value = data.value if data.kind else None
    order.discount_reason = data.reason if data.kind else None
    await recompute(db, order)
    if order.paid_total > order.total:
        raise Conflict("DISCOUNT_BELOW_PAID")
    order.updated_at = datetime.now(UTC)
    await db.flush()
    await _publish(
        db, ctx, order, "discount", {"discount": [None, f"{data.kind}:{data.value}" if data.kind else None]}
    )
    await db.commit()
    return order


async def cancel_order(db: AsyncSession, ctx: HotelContext, order_id: uuid.UUID, reason: str) -> Order:
    order = await get_order(db, ctx.hotel_id, order_id, for_update=True)
    _require_open(order)
    if any(not p.is_void for p in await _payments(db, order.id)):
        raise Conflict("ORDER_HAS_PAYMENTS")
    now = datetime.now(UTC)
    lines = await _lines(db, order.id)
    if any(ln.status not in ("new", "void") for ln in lines):
        _require(ctx, P.RESTAURANT_VOID)  # food already prepared or served
    for ln in lines:
        if ln.status != "void":
            ln.status, ln.void_reason, ln.voided_at, ln.voided_by = "void", reason, now, ctx.actor.user_id
    order.status = "cancelled"
    order.cancel_reason = reason
    order.closed_at, order.closed_by = now, ctx.actor.user_id
    await db.flush()
    await recompute(db, order)
    await db.flush()
    await _publish(db, ctx, order, "cancel", {"status": ["open", "cancelled"], "reason": [None, reason]})
    await db.commit()
    return order


# --- payments ------------------------------------------------------------------------------


async def record_payment(
    db: AsyncSession, ctx: HotelContext, order_id: uuid.UUID, data: Any, idempotency_key: str | None
) -> tuple[Order, Decimal | None]:
    """Returns (order, change due in the tendered currency for cash)."""
    digest = idempotency.digest(f"pos-payment:{order_id}", data.model_dump(mode="json"))
    if idempotency_key and await idempotency.claim(db, ctx, idempotency_key, digest):
        return await get_order(db, ctx.hotel_id, order_id), None
    order = await get_order(db, ctx.hotel_id, order_id, for_update=True)
    _require_open(order)
    lines = await _lines(db, order.id)
    if any(ln.status == "new" for ln in lines):
        raise Conflict("UNSENT_ITEMS")
    await recompute(db, order)
    balance = order.total - order.paid_total
    if balance <= ZERO:
        raise Conflict("NOTHING_TO_PAY")
    hotel = await _hotel(db, ctx.hotel_id)
    base_cur = hotel.currency_code
    now = datetime.now(UTC)
    change: Decimal | None = None

    if data.method == "room_charge":
        rr_id = data.reservation_room_id or order.reservation_room_id
        if rr_id is None:
            raise ValidationFailed(
                "ROOM_REQUIRED", fields=[field_error("reservation_room_id", "ROOM_REQUIRED")]
            )
        rr = await _stay(db, ctx.hotel_id, rr_id, in_house=True)
        if order.paid_total != ZERO:
            raise Conflict("ROOM_CHARGE_FULL_ONLY")  # the whole check goes to the room
        res = await billing.load_reservation(db, ctx.hotel_id, rr.reservation_id, for_update=True)
        outlet = await db.get(Outlet, order.outlet_id)
        assert outlet is not None
        charge = await billing.post_outlet_charge(
            db,
            ctx,
            res,
            reservation_room_id=rr.id,
            name=dict(outlet.name),
            description=order.number,
            net_amount=order.total - order.tax_total,
            tax_lines=order.tax_breakdown,
            service_date=order.business_date,
        )
        payment = OrderPayment(
            id=uuid.uuid4(),
            hotel_id=ctx.hotel_id,
            order_id=order.id,
            method="room_charge",
            amount=balance,
            currency=base_cur,
            exchange_rate=Decimal(1),
            amount_base=balance,
            reservation_room_id=rr.id,
            folio_charge_id=charge.id,
            received_at=now,
            received_by=ctx.actor.user_id,
            is_void=False,
        )
        order.reservation_room_id = rr.id
    else:
        currency = data.currency or base_cur
        rate = await billing.current_rate(db, hotel, currency)
        if data.exchange_rate is not None and data.exchange_rate != rate:
            raise Conflict("EXCHANGE_RATE_CHANGED", params={"currency": currency, "rate": str(rate)})
        amount = data.amount
        amount_base = round_money(amount / rate, base_cur)
        if amount_base <= ZERO:
            raise ValidationFailed("AMOUNT_TOO_SMALL", fields=[field_error("amount", "AMOUNT_TOO_SMALL")])
        tendered = None
        if amount_base > balance:
            if data.method != "cash":
                raise Conflict("PAYMENT_EXCEEDS_BALANCE", params={"balance": str(balance)})
            # Cash: keep the balance, give the rest back as change.
            tendered = amount
            amount = round_money(balance * rate, currency)
            amount_base = balance
            change = tendered - amount
        payment = OrderPayment(
            id=uuid.uuid4(),
            hotel_id=ctx.hotel_id,
            order_id=order.id,
            method=data.method,
            amount=amount,
            currency=currency,
            exchange_rate=rate,
            amount_base=amount_base,
            tendered=tendered,
            reference=data.reference,
            card_brand=data.card_brand,
            card_last4=data.card_last4,
            received_at=now,
            received_by=ctx.actor.user_id,
            is_void=False,
        )
    db.add(payment)
    await db.flush()
    await recompute(db, order)
    if order.paid_total >= order.total:
        order.status = "closed"
        order.closed_at, order.closed_by = now, ctx.actor.user_id
    order.updated_at = now
    await db.flush()
    if idempotency_key:
        await idempotency.bind(db, ctx, idempotency_key, order.id)
    await _publish(
        db,
        ctx,
        order,
        "payment",
        {"payment": [None, f"{payment.method} {payment.amount} {payment.currency}"]},
    )
    await events.emit(
        db, hotel_id=ctx.hotel_id, entity="payment", action="created", entity_id=payment.id, actor=ctx.actor
    )
    await db.commit()
    return order, change


async def void_payment(
    db: AsyncSession, ctx: HotelContext, order_id: uuid.UUID, payment_id: uuid.UUID, reason: str
) -> Order:
    _require(ctx, P.RESTAURANT_VOID)
    order = await get_order(db, ctx.hotel_id, order_id, for_update=True)
    if order.status == "cancelled":
        raise Conflict("ORDER_CLOSED", params={"status": order.status})
    payment = (
        await db.scalars(
            select(OrderPayment).where(OrderPayment.id == payment_id, OrderPayment.order_id == order.id)
        )
    ).one_or_none()
    if payment is None:
        raise NotFound("PAYMENT_NOT_FOUND")
    if payment.is_void:
        raise Conflict("ALREADY_VOID")
    now = datetime.now(UTC)
    if payment.folio_charge_id:
        charge = await db.get(FolioCharge, payment.folio_charge_id)
        assert charge is not None
        res = await billing.load_reservation(db, ctx.hotel_id, charge.reservation_id, for_update=True)
        await billing.void_charge_tx(db, ctx, res, charge, f"{order.number}: {reason}")
    payment.is_void, payment.void_reason, payment.voided_at, payment.voided_by = (
        True,
        reason,
        now,
        ctx.actor.user_id,
    )
    await db.flush()
    await recompute(db, order)
    if order.status == "closed" and order.paid_total < order.total:
        order.status, order.closed_at, order.closed_by = "open", None, None
    order.updated_at = now
    await db.flush()
    await _publish(
        db,
        ctx,
        order,
        "void_payment",
        {"payment": [str(payment.amount_base), None], "reason": [None, reason]},
    )
    await events.emit(
        db, hotel_id=ctx.hotel_id, entity="payment", action="updated", entity_id=payment.id, actor=ctx.actor
    )
    await db.commit()
    return order


# --- read models ---------------------------------------------------------------------------


async def _guest_refs(db: AsyncSession, rr_ids: set[uuid.UUID]) -> dict[uuid.UUID, dict[str, Any]]:
    if not rr_ids:
        return {}
    rows = (
        await db.execute(
            select(ReservationRoom, Reservation, Guest, Room)
            .join(Reservation, Reservation.id == ReservationRoom.reservation_id)
            .join(Guest, Guest.id == Reservation.booker_guest_id)
            .outerjoin(Room, Room.id == ReservationRoom.room_id)
            .where(ReservationRoom.id.in_(rr_ids))
        )
    ).all()
    return {
        rr.id: {
            "reservation_room_id": rr.id,
            "reservation_id": res.id,
            "reservation_code": res.code,
            "room_number": room.number if room else None,
            "guest_name": f"{g.first_name} {g.last_name}".strip(),
            "in_house": rr.checked_in_at is not None and rr.checked_out_at is None,
        }
        for rr, res, g, room in rows
    }


async def _names(db: AsyncSession, ids: set[uuid.UUID | None]) -> dict[uuid.UUID, str]:
    wanted = {i for i in ids if i}
    if not wanted:
        return {}
    return {u.id: u.full_name for u in await db.scalars(select(User).where(User.id.in_(wanted)))}


async def summaries(db: AsyncSession, orders: list[Order]) -> list[dict[str, Any]]:
    if not orders:
        return []
    ids = [o.id for o in orders]
    counts: dict[uuid.UUID, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for order_id, status, n in (
        await db.execute(
            select(OrderLine.order_id, OrderLine.status, func.count())
            .where(OrderLine.order_id.in_(ids))
            .group_by(OrderLine.order_id, OrderLine.status)
        )
    ).all():
        counts[order_id][status] = n
    table_ids = {o.table_id for o in orders if o.table_id}
    labels = (
        {t.id: t.label for t in await db.scalars(select(DiningTable).where(DiningTable.id.in_(table_ids)))}
        if table_ids
        else {}
    )
    guests = await _guest_refs(db, {o.reservation_room_id for o in orders if o.reservation_room_id})
    names = await _names(db, {o.opened_by for o in orders})
    return [
        {
            "id": o.id,
            "outlet_id": o.outlet_id,
            "number": o.number,
            "business_date": o.business_date,
            "table_id": o.table_id,
            "table_label": labels.get(o.table_id) if o.table_id else None,
            "order_type": o.order_type,
            "covers": o.covers,
            "status": o.status,
            "total": o.total,
            "paid_total": o.paid_total,
            "balance": o.total - o.paid_total,
            "lines_new": counts[o.id]["new"],
            "lines_waiting": counts[o.id]["sent"] + counts[o.id]["preparing"],
            "lines_ready": counts[o.id]["ready"],
            "opened_at": o.created_at,
            "opened_by_name": names.get(o.opened_by) if o.opened_by else None,
            "guest": guests.get(o.reservation_room_id) if o.reservation_room_id else None,
            "version": o.version,
        }
        for o in orders
    ]


async def order_out(db: AsyncSession, order: Order, change_due: Decimal | None = None) -> dict[str, Any]:
    await db.refresh(order)
    summary = (await summaries(db, [order]))[0]
    outlet = await db.get(Outlet, order.outlet_id)
    assert outlet is not None
    payments = await _payments(db, order.id)
    names = await _names(db, {p.received_by for p in payments})
    rooms = await _guest_refs(db, {p.reservation_room_id for p in payments if p.reservation_room_id})
    return {
        **summary,
        "discount_kind": order.discount_kind,
        "discount_value": order.discount_value,
        "discount_reason": order.discount_reason,
        "subtotal": order.subtotal,
        "discount_total": order.discount_total,
        "service_charge": order.service_charge,
        "service_charge_percent": outlet.service_charge_percent,
        "tax_total": order.tax_total,
        "tax_breakdown": order.tax_breakdown,
        "notes": order.notes,
        "closed_at": order.closed_at,
        "cancel_reason": order.cancel_reason,
        "lines": [LineOut.model_validate(ln) for ln in await _lines(db, order.id)],
        "payments": [
            {
                **{
                    f: getattr(p, f)
                    for f in (
                        "id",
                        "method",
                        "amount",
                        "currency",
                        "exchange_rate",
                        "amount_base",
                        "tendered",
                        "reference",
                        "card_brand",
                        "card_last4",
                        "received_at",
                        "is_void",
                        "void_reason",
                    )
                },
                "room_number": rooms[p.reservation_room_id]["room_number"]
                if p.reservation_room_id in rooms
                else None,
                "received_by_name": names.get(p.received_by) if p.received_by else None,
            }
            for p in payments
        ],
        "change_due": change_due,
    }


async def list_orders(
    db: AsyncSession, ctx: HotelContext, *, outlet_id: uuid.UUID | None, status: str | None, day: date | None
) -> list[dict[str, Any]]:
    stmt = select(Order).where(Order.hotel_id == ctx.hotel_id)
    if outlet_id:
        stmt = stmt.where(Order.outlet_id == outlet_id)
    if status:
        stmt = stmt.where(Order.status == status)
    if day:
        stmt = stmt.where(Order.business_date == day)
    elif status != "open":
        stmt = stmt.where(Order.business_date == (await _hotel(db, ctx.hotel_id)).today())
    return await summaries(db, list(await db.scalars(stmt.order_by(Order.created_at.desc()).limit(500))))


async def floor(db: AsyncSession, ctx: HotelContext, outlet_id: uuid.UUID) -> list[dict[str, Any]]:
    await _outlet(db, ctx.hotel_id, outlet_id)
    tables = [t for t in await list_tables(db, ctx.hotel_id, outlet_id) if t.is_active]
    open_orders = list(
        await db.scalars(
            select(Order).where(
                Order.outlet_id == outlet_id, Order.status == "open", Order.table_id.is_not(None)
            )
        )
    )
    by_table = {s["table_id"]: s for s in await summaries(db, open_orders)}
    return [
        {"id": t.id, "label": t.label, "area": t.area, "seats": t.seats, "order": by_table.get(t.id)}
        for t in tables
    ]


async def kitchen(
    db: AsyncSession, ctx: HotelContext, outlet_id: uuid.UUID | None, station: str | None
) -> list[dict]:
    stmt = (
        select(OrderLine, Order)
        .join(Order, Order.id == OrderLine.order_id)
        .where(Order.hotel_id == ctx.hotel_id, OrderLine.status.in_(("sent", "preparing", "ready")))
    )
    if outlet_id:
        stmt = stmt.where(Order.outlet_id == outlet_id)
    if station:
        stmt = stmt.where(OrderLine.station == station)
    rows = (await db.execute(stmt.order_by(OrderLine.sent_at, OrderLine.created_at))).all()
    tickets: dict[uuid.UUID, dict[str, Any]] = {}
    orders = {o.id: o for _, o in rows}
    summary = {s["id"]: s for s in await summaries(db, list(orders.values()))}
    for line, order in rows:
        t = tickets.setdefault(
            order.id,
            {
                "order_id": order.id,
                "number": order.number,
                "table_label": summary[order.id]["table_label"],
                "order_type": order.order_type,
                "covers": order.covers,
                "room_number": (summary[order.id]["guest"] or {}).get("room_number"),
                "lines": [],
            },
        )
        t["lines"].append(LineOut.model_validate(line))
    return list(tickets.values())


async def in_house_guests(db: AsyncSession, ctx: HotelContext, q: str | None) -> list[dict[str, Any]]:
    stmt = (
        select(ReservationRoom.id)
        .join(Reservation, Reservation.id == ReservationRoom.reservation_id)
        .join(Guest, Guest.id == Reservation.booker_guest_id)
        .outerjoin(Room, Room.id == ReservationRoom.room_id)
        .where(
            ReservationRoom.hotel_id == ctx.hotel_id,
            ReservationRoom.checked_in_at.is_not(None),
            ReservationRoom.checked_out_at.is_(None),
        )
    )
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            Room.number.ilike(like)
            | func.concat(Guest.first_name, " ", Guest.last_name).ilike(like)
            | Reservation.code.ilike(like)
        )
    ids = set(await db.scalars(stmt.limit(50)))
    refs = await _guest_refs(db, ids)
    return sorted(refs.values(), key=lambda r: (r["room_number"] or "", r["guest_name"]))


# --- breakfast ----------------------------------------------------------------------------


async def breakfast_list(db: AsyncSession, ctx: HotelContext, day: date | None) -> list[dict[str, Any]]:
    """Guests whose rate includes breakfast and who slept here the night before `day`."""
    hotel = await _hotel(db, ctx.hotel_id)
    day = day or hotel.today()
    night = day - timedelta(days=1)
    rows = (
        await db.execute(
            select(ReservationRoom, Reservation, Guest, Room, RatePlan)
            .join(Reservation, Reservation.id == ReservationRoom.reservation_id)
            .join(Guest, Guest.id == Reservation.booker_guest_id)
            .join(RatePlan, RatePlan.id == ReservationRoom.rate_plan_id)
            .outerjoin(Room, Room.id == ReservationRoom.room_id)
            .where(
                ReservationRoom.hotel_id == ctx.hotel_id,
                ReservationRoom.occupies_inventory.is_(True),
                ReservationRoom.checked_in_at.is_not(None),
                ReservationRoom.arrival <= night,
                ReservationRoom.departure > night,
                RatePlan.meal_plan.in_(BREAKFAST_PLANS),
            )
            .order_by(Room.number)
        )
    ).all()
    marks = {
        m.reservation_room_id: m.covers
        for m in await db.scalars(
            select(BreakfastMark).where(BreakfastMark.hotel_id == ctx.hotel_id, BreakfastMark.day == day)
        )
    }
    return [
        {
            "reservation_room_id": rr.id,
            "reservation_code": res.code,
            "room_number": room.number if room else None,
            "guest_name": f"{g.first_name} {g.last_name}".strip(),
            "adults": rr.adults,
            "children": rr.children,
            "meal_plan": plan.meal_plan,
            "served_covers": marks.get(rr.id),
        }
        for rr, res, g, room, plan in rows
    ]


async def mark_breakfast(db: AsyncSession, ctx: HotelContext, data: Any) -> None:
    hotel = await _hotel(db, ctx.hotel_id)
    day = data.day or hotel.today()
    allowed = {r["reservation_room_id"]: r for r in await breakfast_list(db, ctx, day)}
    row = allowed.get(data.reservation_room_id)
    if row is None:
        raise Conflict("BREAKFAST_NOT_INCLUDED")
    if data.covers > row["adults"] + row["children"]:
        raise ValidationFailed("TOO_MANY_COVERS", params={"max": row["adults"] + row["children"]})
    mark = await db.get(BreakfastMark, (data.reservation_room_id, day))
    if mark is None:
        db.add(
            BreakfastMark(
                hotel_id=ctx.hotel_id,
                reservation_room_id=data.reservation_room_id,
                day=day,
                covers=data.covers,
                marked_by=ctx.actor.user_id,
            )
        )
    else:
        mark.covers, mark.marked_by, mark.marked_at = data.covers, ctx.actor.user_id, datetime.now(UTC)
    await db.flush()
    await events.emit(
        db, hotel_id=ctx.hotel_id, entity="restaurant_order", action="breakfast", actor=ctx.actor
    )
    await db.commit()


async def unmark_breakfast(db: AsyncSession, ctx: HotelContext, rr_id: uuid.UUID, day: date | None) -> None:
    hotel = await _hotel(db, ctx.hotel_id)
    mark = await db.get(BreakfastMark, (rr_id, day or hotel.today()))
    if mark is None or mark.hotel_id != ctx.hotel_id:
        raise NotFound("BREAKFAST_MARK_NOT_FOUND")
    await db.delete(mark)
    await events.emit(
        db, hotel_id=ctx.hotel_id, entity="restaurant_order", action="breakfast", actor=ctx.actor
    )
    await db.commit()


# --- sales report -------------------------------------------------------------------------


async def sales_report(
    db: AsyncSession, ctx: HotelContext, start: date, end: date, outlet_id: uuid.UUID | None
) -> dict[str, Any]:
    if not (ctx.has(P.RESTAURANT_MANAGE) or ctx.has(P.REPORTS_FINANCIAL)):
        raise Forbidden("PERMISSION_DENIED", params={"permission": P.RESTAURANT_MANAGE})
    if end < start or (end - start).days > 366:
        raise ValidationFailed("INVALID_RANGE", params={"max_days": 366})
    stmt = select(Order).where(
        Order.hotel_id == ctx.hotel_id,
        Order.status == "closed",
        Order.business_date >= start,
        Order.business_date <= end,
    )
    if outlet_id:
        stmt = stmt.where(Order.outlet_id == outlet_id)
    orders = list(await db.scalars(stmt))
    ids = [o.id for o in orders]
    total = sum((o.total for o in orders), ZERO)
    cur = (await _hotel(db, ctx.hotel_id)).currency_code
    by_category: dict[Any, dict[str, Any]] = {}
    items: dict[Any, dict[str, Any]] = {}
    voided = 0
    voided_amount = ZERO
    if ids:
        categories = {
            c.id: c.name
            for c in await db.scalars(select(MenuCategory).where(MenuCategory.hotel_id == ctx.hotel_id))
        }
        for ln in await db.scalars(select(OrderLine).where(OrderLine.order_id.in_(ids))):
            if ln.status == "void":
                voided += 1
                voided_amount += ln.amount
                continue
            c = by_category.setdefault(
                ln.category_id,
                {
                    "category_id": ln.category_id,
                    "name": categories.get(ln.category_id, {}),
                    "quantity": 0,
                    "amount": ZERO,
                },
            )
            c["quantity"] += ln.quantity
            c["amount"] += ln.amount
            key = ln.menu_item_id or ln.name.get("en")
            it = items.setdefault(
                key, {"menu_item_id": ln.menu_item_id, "name": ln.name, "quantity": 0, "amount": ZERO}
            )
            it["quantity"] += ln.quantity
            it["amount"] += ln.amount
    methods: dict[tuple[str, str], dict[str, Any]] = {}
    if ids:
        for p in await db.scalars(
            select(OrderPayment).where(OrderPayment.order_id.in_(ids), OrderPayment.is_void.is_(False))
        ):
            m = methods.setdefault(
                (p.method, p.currency),
                {"method": p.method, "currency": p.currency, "count": 0, "amount": ZERO, "amount_base": ZERO},
            )
            m["count"] += 1
            m["amount"] += p.amount
            m["amount_base"] += p.amount_base
    covers = sum(o.covers for o in orders)
    return {
        "start": start,
        "end": end,
        "orders": len(orders),
        "covers": covers,
        "subtotal": sum((o.subtotal for o in orders), ZERO),
        "discounts": sum((o.discount_total for o in orders), ZERO),
        "service_charge": sum((o.service_charge for o in orders), ZERO),
        "taxes": sum((o.tax_total for o in orders), ZERO),
        "total": total,
        "average_check": round_money(total / len(orders), cur) if orders else ZERO,
        "voided_lines": voided,
        "voided_amount": voided_amount,
        "by_category": sorted(by_category.values(), key=lambda c: -c["amount"]),
        "top_items": sorted(items.values(), key=lambda i: (-i["quantity"], -i["amount"]))[:20],
        "by_method": sorted(methods.values(), key=lambda m: (m["method"], m["currency"])),
    }


# --- documents ----------------------------------------------------------------------------


async def bill_pdf(
    db: AsyncSession, ctx: HotelContext, order_id: uuid.UUID, language: str | None
) -> tuple[bytes, str]:
    from app.modules.billing import documents, pdf

    order = await get_order(db, ctx.hotel_id, order_id)
    hotel = await _hotel(db, ctx.hotel_id)
    outlet = await db.get(Outlet, order.outlet_id)
    assert outlet is not None
    summary = (await summaries(db, [order]))[0]
    lang = documents.pick_language(language, None, hotel)
    tr = documents.Tr(lang, hotel.default_language)
    cur = hotel.currency_code
    lines = [ln for ln in await _lines(db, order.id) if ln.status != "void"]
    payments = [p for p in await _payments(db, order.id) if not p.is_void]
    rooms = await _guest_refs(db, {p.reservation_room_id for p in payments if p.reservation_room_id})
    meta = [[tr("order_type"), tr("order_types." + order.order_type)]]
    if summary["table_label"]:
        meta.append([tr("table"), summary["table_label"]])
    meta.append([tr("covers"), str(order.covers)])
    if summary["opened_by_name"]:
        meta.append([tr("server"), summary["opened_by_name"]])
    if summary["guest"]:
        meta.append(
            [
                tr("guest"),
                f"{summary['guest']['guest_name']} · "
                + tr("room_number", number=summary["guest"]["room_number"]),
            ]
        )
    totals: list[list[Any]] = [[tr("subtotal"), tr.money(order.subtotal, cur), False]]
    if order.discount_total:
        totals.append([tr("discount"), tr.money(-order.discount_total, cur), False])
    if order.service_charge:
        totals.append(
            [
                tr("service_charge", rate=tr.number(outlet.service_charge_percent)),
                tr.money(order.service_charge, cur),
                False,
            ]
        )
    for t in order.tax_breakdown:
        name = (tr.text(t.get("name")) or t["code"]) + f" {tr.number(Decimal(t['rate']))}%"
        amount = tr.money(Decimal(t["amount"]), cur)
        totals.append([tr("tax_included", name=name) if t["is_inclusive"] else name, amount, False])
    totals.append([tr("total"), tr.money(order.total, cur), True])
    if payments:
        totals.append([tr("paid"), tr.money(order.paid_total, cur), False])
        change = sum((p.tendered - p.amount for p in payments if p.tendered and p.currency == cur), ZERO)
        if change:
            totals.append([tr("change"), tr.money(change, cur), False])
    if order.total - order.paid_total > 0:
        totals.append([tr("balance_due"), tr.money(order.total - order.paid_total, cur), True])

    def pay_label(p: OrderPayment) -> str:
        if p.method == "room_charge":
            room = rooms.get(p.reservation_room_id, {}).get("room_number") if p.reservation_room_id else None
            return tr("room_charge", room=room or "—")
        label = tr("method." + p.method)
        if p.card_last4:
            label += " · " + tr(
                "card", brand=tr("card_brand." + (p.card_brand or "other")), last4=p.card_last4
            )
        return label

    doc = {
        "kind": "restaurant",
        "language": lang,
        "title": tr("title.restaurant_receipt" if order.status == "closed" else "title.bill"),
        "number": order.number,
        "issue_date": tr.date(order.business_date),
        "hotel": documents._hotel_block(hotel, tr),
        "bill_to_label": tr("outlet"),
        "bill_to": [tr.text(outlet.name)],
        "meta": meta,
        "page_css": documents._page_css(tr("page_of", page="\x00page", pages="\x00pages")),
        "labels": {
            k: tr(k)
            for k in (
                "number",
                "issue_date",
                "description",
                "quantity",
                "unit_price",
                "amount",
                "payments",
                "void_stamp",
            )
        },
        "lines": [
            {
                "description": tr.text(ln.name),
                "detail": ln.notes or "",
                "quantity": str(ln.quantity),
                "unit_price": tr.money(ln.unit_price, cur),
                "amount": tr.money(ln.amount, cur),
                "void": False,
            }
            for ln in lines
        ],
        "totals": totals,
        "payments": [
            {
                "date": tr.date(p.received_at.astimezone(hotel.zone).date()),
                "number": "",
                "label": pay_label(p),
                "amount": tr.money(p.amount_base, cur)
                + (f" ({tr.money(p.amount, p.currency)})" if p.currency != cur else ""),
            }
            for p in payments
        ],
        "notes": ([tr("unpaid_bill_note")] if order.status != "closed" else []) + [tr("thanks")],
        "is_void": order.status == "cancelled",
    }
    return await pdf.render_pdf(doc), order.number
