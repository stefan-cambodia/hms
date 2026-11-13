from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.core.errors import Forbidden
from app.core.permissions import P
from app.core.schemas import LanguageCode
from app.modules.accounts import service
from app.modules.accounts.schemas import (
    AccountDetailOut,
    AccountIn,
    AccountOut,
    AccountPaymentIn,
    AccountUpdate,
    TransferIn,
    VoidIn,
)
from app.modules.auth.deps import DB, hotel_ctx
from app.modules.billing import service as billing
from app.modules.billing.schemas import FolioOut

router = APIRouter(prefix="/hotels/{hotel_id}", tags=["company accounts"])

View = hotel_ctx(P.ACCOUNTS_VIEW)
Manage = hotel_ctx(P.ACCOUNTS_MANAGE)
Receive = hotel_ctx(P.PAYMENTS_RECORD)
VoidPayment = hotel_ctx(P.PAYMENTS_VOID)


def _require(ctx, permission: P) -> None:
    if not ctx.has(permission):
        raise Forbidden("PERMISSION_DENIED", params={"permission": permission})


@router.get("/company-accounts", response_model=list[AccountOut])
async def list_accounts(
    ctx: View,
    db: DB,
    q: Annotated[str | None, Query(max_length=100)] = None,
    active: bool | None = None,
):
    return await service.list_accounts(db, ctx, q, active)


@router.post("/company-accounts", response_model=AccountDetailOut, status_code=status.HTTP_201_CREATED)
async def create_account(body: AccountIn, ctx: Manage, db: DB):
    acc = await service.create_account(db, ctx, body)
    return await service.detail(db, ctx, acc.id)


@router.get("/company-accounts/{account_id}", response_model=AccountDetailOut)
async def get_account(account_id: uuid.UUID, ctx: View, db: DB):
    return await service.detail(db, ctx, account_id)


@router.patch("/company-accounts/{account_id}", response_model=AccountDetailOut)
async def update_account(account_id: uuid.UUID, body: AccountUpdate, ctx: Manage, db: DB):
    await service.update_account(db, ctx, account_id, body)
    return await service.detail(db, ctx, account_id)


@router.delete("/company-accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(account_id: uuid.UUID, ctx: Manage, db: DB):
    await service.delete_account(db, ctx, account_id)


@router.post(
    "/company-accounts/{account_id}/payments",
    response_model=AccountDetailOut,
    status_code=status.HTTP_201_CREATED,
)
async def receive_payment(account_id: uuid.UUID, body: AccountPaymentIn, ctx: Receive, db: DB):
    """Money received from the company, applied to its open invoices."""
    _require(ctx, P.ACCOUNTS_VIEW)
    await service.receive_payment(db, ctx, account_id, body)
    return await service.detail(db, ctx, account_id)


@router.post("/company-accounts/{account_id}/payments/{payment_id}/void", response_model=AccountDetailOut)
async def void_payment(account_id: uuid.UUID, payment_id: uuid.UUID, body: VoidIn, ctx: VoidPayment, db: DB):
    _require(ctx, P.ACCOUNTS_VIEW)
    await service.void_payment(db, ctx, account_id, payment_id, body.reason)
    return await service.detail(db, ctx, account_id)


@router.get("/company-accounts/{account_id}/statement.pdf")
async def statement_pdf(
    account_id: uuid.UUID, ctx: View, db: DB, language: Annotated[LanguageCode | None, Query()] = None
):
    from app.modules.accounts import pdf

    content, name = await pdf.statement(db, ctx, account_id, language)
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{name}.pdf"', "Cache-Control": "no-store"},
    )


@router.post("/reservations/{res_id}/transfer-to-account", response_model=FolioOut)
async def transfer(res_id: uuid.UUID, body: TransferIn, ctx: Receive, db: DB):
    """Settle the folio by transferring its balance to the reservation's company."""
    res, _ = await service.transfer(db, ctx, res_id, body)
    return await billing.folio_out(db, res)
