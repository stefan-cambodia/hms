from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Header, Query, Response, status

from app.core.permissions import P
from app.core.schemas import LanguageCode
from app.modules.auth.deps import DB, hotel_ctx
from app.modules.restaurant import service
from app.modules.restaurant.schemas import (
    AvailabilityIn,
    BreakfastMarkIn,
    BreakfastRow,
    CancelIn,
    CategoryIn,
    CategoryOut,
    CategoryUpdate,
    DiscountIn,
    FloorTable,
    GuestRef,
    ItemIn,
    ItemOut,
    ItemUpdate,
    KitchenTicket,
    LinesIn,
    LineStatusIn,
    LineUpdate,
    OrderIn,
    OrderOut,
    OrderSummary,
    OrderUpdate,
    OutletIn,
    OutletOut,
    OutletUpdate,
    PaymentIn,
    SalesReport,
    TableIn,
    TableOut,
    TableUpdate,
    VoidIn,
)

router = APIRouter(prefix="/hotels/{hotel_id}/restaurant", tags=["restaurant"])

View = hotel_ctx(P.RESTAURANT_VIEW)
Order_ = hotel_ctx(P.RESTAURANT_ORDER)
Settle = hotel_ctx(P.RESTAURANT_SETTLE)
Manage = hotel_ctx(P.RESTAURANT_MANAGE)
IdempotencyKey = Annotated[str | None, Header(max_length=100)]


# --- configuration -----------------------------------------------------------------------


@router.get("/outlets", response_model=list[OutletOut])
async def list_outlets(ctx: View, db: DB):
    return await service.list_outlets(db, ctx.hotel_id)


@router.post("/outlets", response_model=OutletOut, status_code=status.HTTP_201_CREATED)
async def create_outlet(body: OutletIn, ctx: Manage, db: DB):
    return await service.create_outlet(db, ctx, body)


@router.patch("/outlets/{outlet_id}", response_model=OutletOut)
async def update_outlet(outlet_id: uuid.UUID, body: OutletUpdate, ctx: Manage, db: DB):
    return await service.update_outlet(db, ctx, outlet_id, body)


@router.delete("/outlets/{outlet_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_outlet(outlet_id: uuid.UUID, ctx: Manage, db: DB):
    await service.delete_outlet(db, ctx, outlet_id)


@router.get("/categories", response_model=list[CategoryOut])
async def list_categories(ctx: View, db: DB, outlet_id: uuid.UUID | None = None):
    return await service.list_categories(db, ctx.hotel_id, outlet_id)


@router.post("/categories", response_model=CategoryOut, status_code=status.HTTP_201_CREATED)
async def create_category(body: CategoryIn, ctx: Manage, db: DB):
    return await service.create_category(db, ctx, body)


@router.patch("/categories/{category_id}", response_model=CategoryOut)
async def update_category(category_id: uuid.UUID, body: CategoryUpdate, ctx: Manage, db: DB):
    return await service.update_category(db, ctx, category_id, body)


@router.delete("/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_category(category_id: uuid.UUID, ctx: Manage, db: DB):
    await service.delete_category(db, ctx, category_id)


@router.get("/menu-items", response_model=list[ItemOut])
async def list_items(ctx: View, db: DB, outlet_id: uuid.UUID | None = None):
    return await service.list_items(db, ctx.hotel_id, outlet_id)


@router.post("/menu-items", response_model=ItemOut, status_code=status.HTTP_201_CREATED)
async def create_item(body: ItemIn, ctx: Manage, db: DB):
    return await service.create_item(db, ctx, body)


@router.patch("/menu-items/{item_id}", response_model=ItemOut)
async def update_item(item_id: uuid.UUID, body: ItemUpdate, ctx: Manage, db: DB):
    return await service.update_item(db, ctx, item_id, body)


@router.post("/menu-items/{item_id}/availability", response_model=ItemOut)
async def set_availability(item_id: uuid.UUID, body: AvailabilityIn, ctx: View, db: DB):
    return await service.set_availability(db, ctx, item_id, body.is_available)


@router.delete("/menu-items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(item_id: uuid.UUID, ctx: Manage, db: DB):
    await service.delete_item(db, ctx, item_id)


@router.get("/tables", response_model=list[TableOut])
async def list_tables(ctx: View, db: DB, outlet_id: uuid.UUID | None = None):
    return await service.list_tables(db, ctx.hotel_id, outlet_id)


@router.post("/tables", response_model=TableOut, status_code=status.HTTP_201_CREATED)
async def create_table(body: TableIn, ctx: Manage, db: DB):
    return await service.create_table(db, ctx, body)


@router.patch("/tables/{table_id}", response_model=TableOut)
async def update_table(table_id: uuid.UUID, body: TableUpdate, ctx: Manage, db: DB):
    return await service.update_table(db, ctx, table_id, body)


@router.delete("/tables/{table_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_table(table_id: uuid.UUID, ctx: Manage, db: DB):
    await service.delete_table(db, ctx, table_id)


# --- service ------------------------------------------------------------------------------


@router.get("/floor", response_model=list[FloorTable])
async def floor(ctx: View, db: DB, outlet_id: uuid.UUID):
    return await service.floor(db, ctx, outlet_id)


@router.get("/orders", response_model=list[OrderSummary])
async def list_orders(
    ctx: View,
    db: DB,
    outlet_id: uuid.UUID | None = None,
    status_: Annotated[Literal["open", "closed", "cancelled"] | None, Query(alias="status")] = None,
    day: date | None = None,
):
    return await service.list_orders(db, ctx, outlet_id=outlet_id, status=status_, day=day)


@router.post("/orders", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
async def open_order(body: OrderIn, ctx: Order_, db: DB):
    return await service.order_out(db, await service.open_order(db, ctx, body))


@router.get("/orders/{order_id}", response_model=OrderOut)
async def get_order(order_id: uuid.UUID, ctx: View, db: DB):
    return await service.order_out(db, await service.get_order(db, ctx.hotel_id, order_id))


@router.patch("/orders/{order_id}", response_model=OrderOut)
async def update_order(order_id: uuid.UUID, body: OrderUpdate, ctx: Order_, db: DB):
    return await service.order_out(db, await service.update_order(db, ctx, order_id, body))


@router.post("/orders/{order_id}/lines", response_model=OrderOut)
async def add_lines(
    order_id: uuid.UUID, body: LinesIn, ctx: Order_, db: DB, idempotency_key: IdempotencyKey = None
):
    return await service.order_out(db, await service.add_lines(db, ctx, order_id, body, idempotency_key))


@router.patch("/orders/{order_id}/lines/{line_id}", response_model=OrderOut)
async def update_line(order_id: uuid.UUID, line_id: uuid.UUID, body: LineUpdate, ctx: Order_, db: DB):
    return await service.order_out(db, await service.update_line(db, ctx, order_id, line_id, body))


@router.delete("/orders/{order_id}/lines/{line_id}", response_model=OrderOut)
async def remove_line(order_id: uuid.UUID, line_id: uuid.UUID, ctx: Order_, db: DB):
    return await service.order_out(db, await service.remove_line(db, ctx, order_id, line_id))


@router.post("/orders/{order_id}/lines/{line_id}/status", response_model=OrderOut)
async def line_status(order_id: uuid.UUID, line_id: uuid.UUID, body: LineStatusIn, ctx: View, db: DB):
    return await service.order_out(db, await service.set_line_status(db, ctx, order_id, line_id, body.status))


@router.post("/orders/{order_id}/lines/{line_id}/void", response_model=OrderOut)
async def void_line(order_id: uuid.UUID, line_id: uuid.UUID, body: VoidIn, ctx: View, db: DB):
    return await service.order_out(db, await service.void_line(db, ctx, order_id, line_id, body.reason))


@router.post("/orders/{order_id}/send", response_model=OrderOut)
async def send(order_id: uuid.UUID, ctx: Order_, db: DB):
    return await service.order_out(db, await service.send(db, ctx, order_id))


@router.post("/orders/{order_id}/served", response_model=OrderOut)
async def served(order_id: uuid.UUID, ctx: Order_, db: DB):
    return await service.order_out(db, await service.serve_ready(db, ctx, order_id))


@router.post("/orders/{order_id}/discount", response_model=OrderOut)
async def discount(order_id: uuid.UUID, body: DiscountIn, ctx: View, db: DB):
    return await service.order_out(db, await service.set_discount(db, ctx, order_id, body))


@router.post("/orders/{order_id}/cancel", response_model=OrderOut)
async def cancel(order_id: uuid.UUID, body: CancelIn, ctx: Order_, db: DB):
    return await service.order_out(db, await service.cancel_order(db, ctx, order_id, body.reason))


@router.post("/orders/{order_id}/payments", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
async def pay(
    order_id: uuid.UUID, body: PaymentIn, ctx: Settle, db: DB, idempotency_key: IdempotencyKey = None
):
    order, change = await service.record_payment(db, ctx, order_id, body, idempotency_key)
    return await service.order_out(db, order, change)


@router.post("/orders/{order_id}/payments/{payment_id}/void", response_model=OrderOut)
async def void_payment(order_id: uuid.UUID, payment_id: uuid.UUID, body: VoidIn, ctx: View, db: DB):
    return await service.order_out(db, await service.void_payment(db, ctx, order_id, payment_id, body.reason))


@router.get("/orders/{order_id}/bill.pdf")
async def bill_pdf(
    order_id: uuid.UUID, ctx: View, db: DB, language: Annotated[LanguageCode | None, Query()] = None
):
    content, name = await service.bill_pdf(db, ctx, order_id, language)
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{name}.pdf"', "Cache-Control": "no-store"},
    )


@router.get("/kitchen", response_model=list[KitchenTicket])
async def kitchen(
    ctx: View, db: DB, outlet_id: uuid.UUID | None = None, station: Literal["kitchen", "bar"] | None = None
):
    return await service.kitchen(db, ctx, outlet_id, station)


@router.get("/in-house", response_model=list[GuestRef])
async def in_house(ctx: Settle, db: DB, q: Annotated[str | None, Query(max_length=100)] = None):
    return await service.in_house_guests(db, ctx, q)


@router.get("/breakfast", response_model=list[BreakfastRow])
async def breakfast(ctx: View, db: DB, day: date | None = None):
    return await service.breakfast_list(db, ctx, day)


@router.post("/breakfast", status_code=status.HTTP_204_NO_CONTENT)
async def mark_breakfast(body: BreakfastMarkIn, ctx: Order_, db: DB):
    await service.mark_breakfast(db, ctx, body)


@router.delete("/breakfast/{reservation_room_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unmark_breakfast(reservation_room_id: uuid.UUID, ctx: Order_, db: DB, day: date | None = None):
    await service.unmark_breakfast(db, ctx, reservation_room_id, day)


@router.get("/sales", response_model=SalesReport)
async def sales(ctx: View, db: DB, start: date, end: date, outlet_id: uuid.UUID | None = None):
    return await service.sales_report(db, ctx, start, end, outlet_id)
