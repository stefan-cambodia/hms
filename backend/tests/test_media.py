"""Photos and logos: validation and re-encoding of uploads, permissions per
owner, ordering, limits, deletion, and the logo on PDF documents."""

from __future__ import annotations

import io
import struct
import zlib

from PIL import ExifTags, Image
from pypdf import PdfReader
from sqlalchemy import text

from app.core.db import owner_sessionmaker
from tests.conftest import Api, error_code
from tests.test_billing import book, hotel  # noqa: F401  (fixture)


def jpeg(width: int, height: int, *, gps: bool = False, orientation: int | None = None) -> bytes:
    img = Image.new("RGB", (width, height), (200, 110, 40))
    img.paste((30, 60, 160), (0, 0, width // 2, height // 3))
    exif = Image.Exif()
    if orientation:
        exif[ExifTags.Base.Orientation] = orientation
    if gps:
        exif[ExifTags.Base.ImageDescription] = "front desk camera"
        gps_ifd = exif.get_ifd(ExifTags.IFD.GPSInfo)
        gps_ifd[ExifTags.GPS.GPSLatitudeRef] = "N"
        gps_ifd[ExifTags.GPS.GPSLatitude] = (11.0, 33.0, 24.0)
        gps_ifd[ExifTags.GPS.GPSLongitudeRef] = "E"
        gps_ifd[ExifTags.GPS.GPSLongitude] = (104.0, 55.0, 12.0)
    out = io.BytesIO()
    img.save(out, "JPEG", quality=90, exif=exif.tobytes())
    return out.getvalue()


def png(width: int, height: int, *, alpha: bool = False, color=(20, 120, 110)) -> bytes:
    img = Image.new("RGBA" if alpha else "RGB", (width, height), (*color, 0) if alpha else color)
    img.paste((*color, 255) if alpha else color, (width // 4, height // 4, width * 3 // 4, height * 3 // 4))
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


def png_claiming(width: int, height: int) -> bytes:
    """A tiny PNG whose header claims a huge canvas (decompression bomb)."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(b"\x00" * 64))
        + chunk(b"IEND", b"")
    )


async def upload(api: Api, owner_type: str, owner_id: str | None, content: bytes, name: str = "photo.jpg"):
    data = {"owner_type": owner_type}
    if owner_id:
        data["owner_id"] = owner_id
    return await api.client.post(
        api.h("/media"), data=data, files={"file": (name, content, "application/octet-stream")}
    )


async def listing(api: Api, owner_type: str, owner_id: str | None = None):
    params = {"owner_type": owner_type, **({"owner_id": owner_id} if owner_id else {})}
    return await api.get(api.h("/media"), params=params)


async def room_type(admin: Api, code: str = "DLX") -> str:
    r = await admin.post(
        admin.h("/room-types"),
        {
            "code": code,
            "name": {"en": "Deluxe"},
            "base_occupancy": 2,
            "max_occupancy": 2,
            "max_adults": 2,
            "max_children": 0,
            "base_price": "90.00",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def maintenance_request(api: Api) -> str:
    r = await api.post(api.h("/maintenance-requests"), {"location": "Lobby", "title": "Leaking pipe"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def pdf_images(content: bytes) -> list[tuple[int, int]]:
    return [img.image.size for page in PdfReader(io.BytesIO(content)).pages for img in page.images]


async def test_photos_are_re_encoded_without_metadata(admin: Api):
    rt = await room_type(admin)
    original = jpeg(3000, 2000, gps=True, orientation=6)
    exif = Image.open(io.BytesIO(original)).getexif()
    assert exif.get_ifd(ExifTags.IFD.GPSInfo) and exif[ExifTags.Base.Orientation] == 6

    r = await upload(admin, "room_type", rt, original, name="../../etc/IMG_0042.JPG")
    assert r.status_code == 201, r.text
    photo = r.json()
    # Turned upright (orientation 6 = portrait) and scaled down to 2048 px.
    assert photo["height"] == 2048 and 1360 <= photo["width"] <= 1370
    assert photo["content_type"] == "image/jpeg" and photo["kind"] == "photo"
    assert photo["filename"] == "IMG_0042.jpg"
    assert photo["owner_type"] == "room_type" and photo["owner_id"] == rt
    assert photo["uploaded_by_name"] and photo["size"] < len(original)

    full = await admin.get(photo["url"])
    assert full.status_code == 200
    assert full.headers["content-type"] == "image/jpeg"
    assert full.headers["x-content-type-options"] == "nosniff"
    assert full.headers["cache-control"] == "private, max-age=86400"
    stored = Image.open(io.BytesIO(full.content))
    assert stored.size == (photo["width"], photo["height"])
    # No EXIF at all (no GPS position, no camera data, no description), no profile.
    assert not stored.getexif() and "icc_profile" not in stored.info and "exif" not in stored.info

    thumb = await admin.get(photo["thumbnail_url"])
    assert thumb.status_code == 200 and max(Image.open(io.BytesIO(thumb.content)).size) == 480
    again = await admin.get(photo["url"], headers={"If-None-Match": full.headers["etag"]})
    assert again.status_code == 304 and not again.content

    listed = (await listing(admin, "room_type", rt)).json()
    assert [p["id"] for p in listed] == [photo["id"]]


async def test_unsafe_or_unreadable_files_are_refused(admin: Api):
    rt = await room_type(admin)
    cases = [
        (b"<svg><script>alert(1)</script></svg>", "IMAGE_TYPE_NOT_SUPPORTED"),
        (b"%PDF-1.7 not an image", "IMAGE_TYPE_NOT_SUPPORTED"),
        (b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic", "IMAGE_TYPE_NOT_SUPPORTED"),
        (b"GIF89a\x01\x00\x01\x00\x00\x00\x00;", "IMAGE_TYPE_NOT_SUPPORTED"),
        (jpeg(800, 600)[:1500], "IMAGE_UNREADABLE"),
        (b"", "IMAGE_UNREADABLE"),
        (png_claiming(9000, 8000), "IMAGE_DIMENSIONS_TOO_LARGE"),  # 72 MP
        (png_claiming(30000, 30000), "IMAGE_DIMENSIONS_TOO_LARGE"),  # Pillow's bomb limit
    ]
    for content, code in cases:
        r = await upload(admin, "room_type", rt, content, name="innocent.jpg")
        assert r.status_code == 422 and error_code(r) == code, (content[:12], r.text)

    too_big = b"\xff\xd8\xff" + b"\x00" * (15 * 1024 * 1024)
    r = await upload(admin, "room_type", rt, too_big)
    assert r.status_code == 413 and error_code(r) == "FILE_TOO_LARGE"
    # Larger than any legitimate request: refused before the body is read.
    r = await admin.client.post(
        admin.h("/media"),
        content=b"x" * (17 * 1024 * 1024),
        headers={"Content-Type": "multipart/form-data; boundary=x"},
    )
    assert r.status_code == 413 and error_code(r) == "FILE_TOO_LARGE"
    assert (await listing(admin, "room_type", rt)).json() == []

    r = await upload(admin, "room_type", None, jpeg(100, 100))
    assert r.status_code == 422 and error_code(r) == "MEDIA_OWNER_REQUIRED"
    r = await upload(admin, "room_type", admin.hotel_id, jpeg(100, 100))  # not a room category
    assert r.status_code == 404 and error_code(r) == "MEDIA_OWNER_NOT_FOUND"


async def test_logo_keeps_transparency_and_replacing_it_archives_the_old_one(admin: Api):
    first = await upload(admin, "hotel", None, png(600, 200, alpha=True), name="logo.png")
    assert first.status_code == 201, first.text
    logo = first.json()
    assert logo["kind"] == "logo" and logo["content_type"] == "image/png"
    assert logo["owner_type"] == "hotel" and logo["owner_id"] == admin.hotel_id
    stored = Image.open(io.BytesIO((await admin.get(logo["url"])).content))
    assert stored.mode == "RGBA" and stored.getpixel((0, 0))[3] == 0  # transparent corner kept

    # A JPEG logo is fine too; it replaces the current one.
    second = (await upload(admin, "hotel", None, jpeg(300, 300), name="logo.jpg")).json()
    assert [m["id"] for m in (await listing(admin, "hotel")).json()] == [second["id"]]
    assert (await admin.get(logo["url"])).status_code == 404  # archived, no longer served
    assert (await admin.delete(admin.h(f"/media/{second['id']}"))).status_code == 204
    assert (await listing(admin, "hotel")).json() == []
    async with owner_sessionmaker()() as db:
        kept = await db.scalar(text("SELECT count(*) FROM media_files WHERE archived_at IS NOT NULL"))
    assert kept == 2  # for invoices issued with them


async def test_invoices_keep_the_logo_they_were_issued_with(admin: Api, hotel):  # noqa: F811
    wide = (await upload(admin, "hotel", None, png(600, 200, alpha=True))).json()
    res = await book(admin, hotel, 3, 4)
    inv = await admin.post(admin.h(f"/reservations/{res['id']}/invoices"), {"language": "en"})
    assert inv.status_code == 201, inv.text
    invoice_pdf = admin.h(f"/invoices/{inv.json()['id']}/pdf")
    folio_pdf = admin.h(f"/reservations/{res['id']}/folio.pdf")
    assert pdf_images((await admin.get(invoice_pdf)).content) == [(wide["width"], wide["height"])]

    square = (await upload(admin, "hotel", None, png(300, 300))).json()
    assert pdf_images((await admin.get(invoice_pdf)).content) == [(600, 200)]
    assert pdf_images((await admin.get(folio_pdf)).content) == [(square["width"], square["height"])]

    assert (await admin.delete(admin.h(f"/media/{square['id']}"))).status_code == 204
    assert pdf_images((await admin.get(folio_pdf)).content) == []
    assert pdf_images((await admin.get(invoice_pdf)).content) == [(600, 200)]

    # Rendering PDFs (WeasyPrint) must not make uploads accept truncated files.
    r = await upload(admin, "hotel", None, jpeg(800, 600)[:1500])
    assert r.status_code == 422 and error_code(r) == "IMAGE_UNREADABLE"


async def test_permissions_per_owner(admin: Api, user_factory):
    rt = await room_type(admin)
    maid = await user_factory("housekeeping")
    other_maid = await user_factory("housekeeping")
    technician = await user_factory("maintenance")
    waiter = await user_factory("waiter")

    r = await upload(maid, "room_type", rt, jpeg(200, 200))
    assert r.status_code == 403 and error_code(r) == "PERMISSION_DENIED"
    r = await upload(maid, "hotel", None, jpeg(200, 200))
    assert r.status_code == 403
    room_photo = (await upload(admin, "room_type", rt, jpeg(200, 200))).json()
    assert (await listing(waiter, "room_type", rt)).status_code == 200  # hotel information
    assert (await waiter.get(room_photo["thumbnail_url"])).status_code == 200
    assert (await maid.delete(maid.h(f"/media/{room_photo['id']}"))).status_code == 403

    # Whoever reports a problem can attach photos and remove their own.
    req = await maintenance_request(maid)
    mine = (await upload(maid, "maintenance_request", req, jpeg(400, 300))).json()
    theirs = (await upload(other_maid, "maintenance_request", req, jpeg(400, 300))).json()
    assert (await maid.delete(maid.h(f"/media/{theirs['id']}"))).status_code == 403
    assert (await maid.delete(maid.h(f"/media/{mine['id']}"))).status_code == 204
    assert (await technician.delete(technician.h(f"/media/{theirs['id']}"))).status_code == 204
    # Maintenance photos are only shown to staff who see maintenance requests.
    kept = (await upload(technician, "maintenance_request", req, jpeg(400, 300))).json()
    assert (await listing(waiter, "maintenance_request", req)).status_code == 403
    assert (await waiter.get(kept["url"])).status_code == 403
    assert [m["id"] for m in (await listing(maid, "maintenance_request", req)).json()] == [kept["id"]]


async def test_limit_order_and_removal_with_the_owner(admin: Api):
    req = await maintenance_request(admin)
    for i in range(10):
        assert (await upload(admin, "maintenance_request", req, png(40 + i, 40))).status_code == 201
    r = await upload(admin, "maintenance_request", req, png(40, 40))
    assert r.status_code == 409 and error_code(r) == "MEDIA_LIMIT_REACHED"
    assert r.json()["error"]["params"] == {"limit": 10}

    rt = await room_type(admin)
    ids = [(await upload(admin, "room_type", rt, jpeg(120, 80))).json()["id"] for _ in range(3)]
    wanted = [ids[2], ids[0], ids[1]]
    r = await admin.put(admin.h("/media/order"), {"owner_type": "room_type", "owner_id": rt, "ids": wanted})
    assert r.status_code == 200 and [m["id"] for m in r.json()] == wanted
    assert [m["id"] for m in (await listing(admin, "room_type", rt)).json()] == wanted
    r = await admin.put(admin.h("/media/order"), {"owner_type": "room_type", "owner_id": rt, "ids": ids[:2]})
    assert r.status_code == 422 and error_code(r) == "MEDIA_ORDER_MISMATCH"

    assert (await admin.delete(admin.h(f"/room-types/{rt}"))).status_code == 204
    async with owner_sessionmaker()() as db:
        left = await db.scalar(text("SELECT count(*) FROM media_files WHERE room_type_id IS NOT NULL"))
    assert left == 0
    assert (await admin.get(admin.h(f"/media/{ids[0]}/content"))).status_code == 404
