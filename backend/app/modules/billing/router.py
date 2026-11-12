from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Header, Query, Response, status

from app.core.permissions import P
from app.core.schemas import LanguageCode, Page
from app.modules.auth.deps import DB, hotel_ctx
from app.modules.billing import pos, service
from app.modules.billing.schemas import (
    ChargeIn,
    CurrencyIn,
    CurrencyOut,
    CurrencyUpdate,
    FolioOut,
    InvoiceListItem,
    InvoiceOut,
    IssueInvoiceIn,
    PaymentIn,
    PaymentOut,
    PaymentReport,
    VoidIn,
)
from app.modules.restaurant.schemas import GuestRef

router = APIRouter(prefix="/hotels/{hotel_id}", tags=["billing"])

HotelView = hotel_ctx(P.HOTEL_VIEW)
ManageCurrencies = hotel_ctx(P.CONFIG_CURRENCIES)
FolioView = hotel_ctx(P.PAYMENTS_VIEW)
FolioPost = hotel_ctx(P.FOLIO_POST)
FolioAdjust = hotel_ctx(P.FOLIO_ADJUST)
PaymentRecord = hotel_ctx(P.PAYMENTS_RECORD)
PaymentVoid = hotel_ctx(P.PAYMENTS_VOID)
InvoiceView = hotel_ctx(P.INVOICES_VIEW)
InvoiceIssue = hotel_ctx(P.INVOICES_ISSUE)
InvoiceVoid = hotel_ctx(P.INVOICES_VOID)
IdempotencyKey = Annotated[str | None, Header(max_length=100)]
Language = Annotated[LanguageCode | None, Query()]


def _pdf(content: bytes, name: str) -> Response:
    return Response(
        content=content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{name}.pdf"',
            "Cache-Control": "no-store",
        },
    )


# --- guests in house (charging sales to rooms) -----------------------------------------


@router.get("/in-house-guests", response_model=list[GuestRef])
async def in_house_guests(ctx: HotelView, db: DB, q: Annotated[str | None, Query(max_length=100)] = None):
    return await pos.in_house_guests(db, ctx, q)


# --- currencies --------------------------------------------------------------------


@router.get("/currencies", response_model=list[CurrencyOut])
async def list_currencies(ctx: HotelView, db: DB):
    return await service.list_currencies(db, ctx.hotel_id)


@router.post("/currencies", response_model=CurrencyOut, status_code=status.HTTP_201_CREATED)
async def create_currency(body: CurrencyIn, ctx: ManageCurrencies, db: DB):
    return await service.create_currency(db, ctx, body)


@router.patch("/currencies/{currency_id}", response_model=CurrencyOut)
async def update_currency(currency_id: uuid.UUID, body: CurrencyUpdate, ctx: ManageCurrencies, db: DB):
    return await service.update_currency(db, ctx, currency_id, body)


@router.delete("/currencies/{currency_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_currency(currency_id: uuid.UUID, ctx: ManageCurrencies, db: DB):
    await service.delete_currency(db, ctx, currency_id)


# --- folio -------------------------------------------------------------------------


@router.get("/reservations/{res_id}/folio", response_model=FolioOut)
async def get_folio(res_id: uuid.UUID, ctx: FolioView, db: DB):
    return await service.folio_out(db, await service.load_reservation(db, ctx.hotel_id, res_id))


@router.post("/reservations/{res_id}/charges", response_model=FolioOut, status_code=status.HTTP_201_CREATED)
async def post_charge(
    res_id: uuid.UUID, body: ChargeIn, ctx: FolioPost, db: DB, idempotency_key: IdempotencyKey = None
):
    return await service.folio_out(db, await service.post_charge(db, ctx, res_id, body, idempotency_key))


@router.post("/reservations/{res_id}/charges/{charge_id}/void", response_model=FolioOut)
async def void_charge(res_id: uuid.UUID, charge_id: uuid.UUID, body: VoidIn, ctx: FolioAdjust, db: DB):
    return await service.folio_out(db, await service.void_charge(db, ctx, res_id, charge_id, body.reason))


@router.post(
    "/reservations/{res_id}/payments", response_model=PaymentOut, status_code=status.HTTP_201_CREATED
)
async def record_payment(
    res_id: uuid.UUID, body: PaymentIn, ctx: PaymentRecord, db: DB, idempotency_key: IdempotencyKey = None
):
    _, payment = await service.record_payment(db, ctx, res_id, body, idempotency_key)
    return payment


@router.post("/reservations/{res_id}/payments/{payment_id}/void", response_model=FolioOut)
async def void_payment(res_id: uuid.UUID, payment_id: uuid.UUID, body: VoidIn, ctx: PaymentVoid, db: DB):
    return await service.folio_out(db, await service.void_payment(db, ctx, res_id, payment_id, body.reason))


@router.get("/reservations/{res_id}/folio.pdf")
async def folio_pdf(res_id: uuid.UUID, ctx: FolioView, db: DB, language: Language = None):
    return _pdf(*await service.statement_pdf(db, ctx.hotel_id, res_id, language))


@router.get("/reservations/{res_id}/payments/{payment_id}/receipt.pdf")
async def receipt_pdf(
    res_id: uuid.UUID, payment_id: uuid.UUID, ctx: FolioView, db: DB, language: Language = None
):
    return _pdf(*await service.receipt_pdf(db, ctx.hotel_id, res_id, payment_id, language))


@router.get("/payments", response_model=PaymentReport)
async def list_payments(
    ctx: FolioView,
    db: DB,
    start: date | None = None,
    end: date | None = None,
    method: Literal["cash", "card", "bank_transfer", "online", "other"] | None = None,
    currency: Annotated[str | None, Query(pattern=r"^[A-Z]{3}$")] = None,
    include_void: bool = False,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    return await service.list_payments(
        db,
        ctx,
        start=start,
        end=end,
        method=method,
        currency=currency,
        include_void=include_void,
        limit=limit,
        offset=offset,
    )


# --- invoices ----------------------------------------------------------------------


@router.post(
    "/reservations/{res_id}/invoices", response_model=InvoiceOut, status_code=status.HTTP_201_CREATED
)
async def issue_invoice(res_id: uuid.UUID, body: IssueInvoiceIn, ctx: InvoiceIssue, db: DB):
    return service.invoice_out(await service.issue_invoice(db, ctx, res_id, body))


@router.get("/invoices", response_model=Page[InvoiceListItem])
async def list_invoices(
    ctx: InvoiceView,
    db: DB,
    q: Annotated[str | None, Query(max_length=100)] = None,
    status_: Annotated[Literal["issued", "void"] | None, Query(alias="status")] = None,
    start: date | None = None,
    end: date | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    items, total = await service.list_invoices(
        db, ctx, q=q, status=status_, start=start, end=end, limit=limit, offset=offset
    )
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/invoices/{invoice_id}", response_model=InvoiceOut)
async def get_invoice(invoice_id: uuid.UUID, ctx: InvoiceView, db: DB):
    return service.invoice_out(await service.get_invoice(db, ctx.hotel_id, invoice_id))


@router.get("/invoices/{invoice_id}/pdf")
async def invoice_pdf(invoice_id: uuid.UUID, ctx: InvoiceView, db: DB):
    return _pdf(*await service.invoice_pdf(db, ctx.hotel_id, invoice_id))


@router.post("/invoices/{invoice_id}/void", response_model=InvoiceOut)
async def void_invoice(invoice_id: uuid.UUID, body: VoidIn, ctx: InvoiceVoid, db: DB):
    return service.invoice_out(await service.void_invoice(db, ctx, invoice_id, body.reason))
