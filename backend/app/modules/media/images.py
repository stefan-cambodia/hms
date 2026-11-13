"""Validation and re-encoding of uploaded images.

Nothing a device sends is stored as is. An upload must be a JPEG, PNG or WebP
by its first bytes (the file name and the declared type are ignored), small
enough to decode safely, and readable to the end. It is then decoded,
turned upright (EXIF orientation), converted to sRGB, scaled down and
encoded again as JPEG (or PNG for a logo with transparency). The new file
carries no metadata: camera EXIF, GPS position, comments and colour
profiles are all left behind.
"""

from __future__ import annotations

import hashlib
import io
import warnings
from dataclasses import dataclass

from PIL import Image, ImageCms, ImageFile, ImageOps, UnidentifiedImageError

MAX_UPLOAD_BYTES = 15 * 1024 * 1024
# Phone cameras go up to about 48-50 megapixels; anything much larger is
# refused before decoding (a small PNG can claim a gigantic canvas).
MAX_MEGAPIXELS = 64
MAX_PIXELS = MAX_MEGAPIXELS * 1_000_000


@dataclass(frozen=True, slots=True)
class Profile:
    max_side: int
    thumb_side: int
    keep_alpha: bool


PROFILES: dict[str, Profile] = {
    "photo": Profile(max_side=2048, thumb_side=480, keep_alpha=False),
    "logo": Profile(max_side=1024, thumb_side=256, keep_alpha=True),
}


@dataclass(frozen=True, slots=True)
class Processed:
    data: bytes
    thumbnail: bytes
    content_type: str
    width: int
    height: int
    sha256: str


class ImageRejected(Exception):
    def __init__(self, code: str, **params: object) -> None:
        super().__init__(code)
        self.code = code
        self.params = params


def sniff(head: bytes) -> str | None:
    """The image format from its magic bytes, or None if not accepted."""
    if head.startswith(b"\xff\xd8\xff"):
        return "JPEG"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "PNG"
    if len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "WEBP"
    return None


def _has_alpha(img: Image.Image) -> bool:
    return img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info)


def _to_srgb(img: Image.Image) -> Image.Image:
    """RGB or RGBA in sRGB, whatever the source (palette, grey, CMYK, Display P3...)."""
    alpha = _has_alpha(img)
    if img.mode in ("P", "PA", "1", "I", "I;16", "F"):
        img = img.convert("RGBA" if alpha else "RGB")
    icc = img.info.get("icc_profile")
    if icc:
        try:
            img = ImageCms.profileToProfile(
                img,
                ImageCms.ImageCmsProfile(io.BytesIO(icc)),
                ImageCms.createProfile("sRGB"),
                outputMode="RGBA" if alpha else "RGB",
            )
        except (ImageCms.PyCMSError, OSError, ValueError, TypeError):
            pass  # unusable profile: plain conversion below
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA" if alpha else "RGB")
    return img


def _flatten(img: Image.Image) -> Image.Image:
    if img.mode == "RGB":
        return img
    background = Image.new("RGB", img.size, (255, 255, 255))
    background.paste(img, mask=img.getchannel("A"))
    return background


def _encode(img: Image.Image, fmt: str, *, thumbnail: bool) -> bytes:
    out = io.BytesIO()
    if fmt == "PNG":
        img.save(out, "PNG", optimize=True)
    else:
        img.save(out, "JPEG", quality=80 if thumbnail else 85, optimize=True, progressive=True)
    return out.getvalue()


def process(raw: bytes, kind: str) -> Processed:
    """Validate and re-encode one upload. Raises ImageRejected with a stable code."""
    profile = PROFILES[kind]
    # A truncated file must be refused, not completed with grey (a library
    # may have switched this process-wide setting on; see billing/pdf.py).
    ImageFile.LOAD_TRUNCATED_IMAGES = False
    fmt = sniff(raw[:16])
    if fmt is None:
        raise ImageRejected("IMAGE_TYPE_NOT_SUPPORTED")
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        try:
            img = Image.open(io.BytesIO(raw), formats=[fmt])
            if img.width * img.height > MAX_PIXELS:
                raise ImageRejected("IMAGE_DIMENSIONS_TOO_LARGE", max_megapixels=MAX_MEGAPIXELS)
            if fmt == "JPEG":
                # Let the JPEG decoder scale down by 2/4/8 while decoding: far
                # less memory and time for a 48 MP photo.
                img.draft(None, (profile.max_side, profile.max_side))
            img.load()
        except ImageRejected:
            raise
        except (Image.DecompressionBombError, Image.DecompressionBombWarning):
            raise ImageRejected("IMAGE_DIMENSIONS_TOO_LARGE", max_megapixels=MAX_MEGAPIXELS) from None
        except (UnidentifiedImageError, OSError, SyntaxError, ValueError, EOFError):
            raise ImageRejected("IMAGE_UNREADABLE") from None

        img = ImageOps.exif_transpose(img)
        img = _to_srgb(img)
        keep_alpha = profile.keep_alpha and img.mode == "RGBA"
        if not keep_alpha:
            img = _flatten(img)
        img.thumbnail((profile.max_side, profile.max_side), Image.Resampling.LANCZOS)
        # Start from a clean slate: no EXIF, GPS, XMP, comments or colour profile
        # can be carried over into the stored file.
        img.info = {}
        out_fmt = "PNG" if keep_alpha else "JPEG"
        data = _encode(img, out_fmt, thumbnail=False)
        thumb = img.copy()
        thumb.thumbnail((profile.thumb_side, profile.thumb_side), Image.Resampling.LANCZOS)
        thumbnail = _encode(thumb, out_fmt, thumbnail=True)
    return Processed(
        data=data,
        thumbnail=thumbnail,
        content_type="image/png" if out_fmt == "PNG" else "image/jpeg",
        width=img.width,
        height=img.height,
        sha256=hashlib.sha256(data).hexdigest(),
    )
