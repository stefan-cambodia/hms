from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Query, Response
from sqlalchemy import select

from app.core.errors import Forbidden
from app.core.permissions import P
from app.core.schemas import LanguageCode
from app.modules.auth.deps import DB, Auth, hotel_ctx
from app.modules.auth.models import User
from app.modules.nightaudit import pdf, service
from app.modules.nightaudit.schemas import CloseIn

router = APIRouter(prefix="/hotels/{hotel_id}/night-audit", tags=["night audit"])

Run = hotel_ctx(P.NIGHT_AUDIT)
Hotel = hotel_ctx(P.HOTEL_VIEW)


@router.get("")
async def overview(
    ctx: Run, db: DB, date_: Annotated[date | None, Query(alias="date")] = None
) -> dict[str, Any]:
    """What is still open for the day, its figures, and whether it can be closed."""
    return await service.overview(db, ctx, date_)


@router.post("/{day}/close")
async def close(day: date, body: CloseIn, ctx: Run, db: DB) -> dict[str, Any]:
    return await service.close_day(db, ctx, day, notes=body.notes, accept_open_items=body.accept_open_items)


@router.get("/closures")
async def closures(
    ctx: Hotel, db: DB, limit: Annotated[int, Query(ge=1, le=366)] = 30
) -> list[dict[str, Any]]:
    """Closed days, newest first: for the night auditors and report readers."""
    if not (ctx.has(P.NIGHT_AUDIT) or ctx.has(P.REPORTS_VIEW)):
        raise Forbidden("PERMISSION_DENIED", params={"permission": P.NIGHT_AUDIT})
    return await service.history(db, ctx, limit)


@router.get("/{day}/report.pdf")
async def report_pdf(
    day: date, ctx: Hotel, auth: Auth, db: DB, language: LanguageCode | None = None
) -> Response:
    if not (ctx.has(P.NIGHT_AUDIT) or ctx.has(P.REPORTS_VIEW)):
        raise Forbidden("PERMISSION_DENIED", params={"permission": P.NIGHT_AUDIT})
    hotel, closure = await service.closed_report(db, ctx, day)
    name = (
        await db.scalar(select(User.full_name).where(User.id == closure.closed_by))
        if closure.closed_by
        else None
    )
    report = service._hide_money(closure.report, ctx)
    lang = language or auth.user.preferred_language or hotel.default_language
    content = await pdf.render_pdf(pdf.document(hotel, closure, report, name, lang))
    return Response(
        content=content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="day-{day.isoformat()}.pdf"',
            "Cache-Control": "no-store",
        },
    )
