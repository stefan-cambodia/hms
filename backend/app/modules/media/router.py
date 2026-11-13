from __future__ import annotations

import uuid
from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, File, Form, Request, Response, UploadFile, status

from app.core.errors import AppError, ValidationFailed
from app.core.permissions import P
from app.modules.auth.deps import DB, hotel_ctx
from app.modules.media import images, service
from app.modules.media.schemas import MediaOrderIn, MediaOut, OwnerType

router = APIRouter(prefix="/hotels/{hotel_id}", tags=["media"])

# Every hotel member reaches these routes; each owner type then requires its
# own permission (service.RULES), e.g. maintenance photos need maintenance.view.
Member = hotel_ctx(P.HOTEL_VIEW)


@router.get("/media", response_model=list[MediaOut])
async def list_media(ctx: Member, db: DB, owner_type: OwnerType, owner_id: uuid.UUID | None = None):
    files = await service.list_media(db, ctx, owner_type, owner_id)
    return await service.media_out(db, ctx, files)


@router.post("/media", response_model=MediaOut, status_code=status.HTTP_201_CREATED)
async def upload(
    ctx: Member,
    db: DB,
    file: Annotated[UploadFile, File(description="JPEG, PNG or WebP, at most 15 MB")],
    owner_type: Annotated[OwnerType, Form()],
    owner_id: Annotated[uuid.UUID | None, Form()] = None,
):
    target = service.check_upload(ctx, owner_type, owner_id)
    raw = await file.read(images.MAX_UPLOAD_BYTES + 1)
    if len(raw) > images.MAX_UPLOAD_BYTES:
        raise AppError(
            "FILE_TOO_LARGE",
            status_code=413,
            params={"max_mb": images.MAX_UPLOAD_BYTES // (1024 * 1024)},
        )
    if not raw:
        raise ValidationFailed("IMAGE_UNREADABLE")
    image = await service.decode(raw, "logo" if owner_type == "hotel" else "photo")
    m = await service.add(db, ctx, owner_type, target, file.filename, image)
    return (await service.media_out(db, ctx, [m]))[0]


@router.put("/media/order", response_model=list[MediaOut])
async def reorder(body: MediaOrderIn, ctx: Member, db: DB):
    files = await service.reorder(db, ctx, body.owner_type, body.owner_id, body.ids)
    return await service.media_out(db, ctx, files)


@router.get(
    "/media/{media_id}/content",
    response_class=Response,
    responses={200: {"content": {"image/jpeg": {}, "image/png": {}}}, 304: {"description": "Not modified"}},
)
async def media_content(
    media_id: uuid.UUID,
    ctx: Member,
    db: DB,
    request: Request,
    variant: Literal["full", "thumbnail"] = "full",
):
    m, data = await service.content(db, ctx, media_id, variant)
    # A file never changes once stored (a new upload gets a new id), so the
    # browser may keep it; it is revalidated cheaply with the ETag.
    etag = f'"{m.sha256[:40]}-{variant}"'
    headers = {
        "ETag": etag,
        "Cache-Control": "private, max-age=86400",
        "Content-Disposition": f"inline; filename*=UTF-8''{quote(m.filename)}",
    }
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)
    return Response(content=data, media_type=m.content_type, headers=headers)


@router.delete("/media/{media_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_media(media_id: uuid.UUID, ctx: Member, db: DB):
    await service.delete(db, ctx, media_id)
