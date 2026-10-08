"""The drawn signature: a PNG, checked and given a transparent background (Pillow)."""
from __future__ import annotations

import base64
import io
import math

from PIL import Image, ImageChops

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
MAX_DECODE_PIXELS = 8_000_000   # refused before decoding: a tiny file can declare gigabytes
MAX_SIGNATURE_PIXELS = 600_000  # bigger canvases are scaled down to this
NEAR_WHITE = 235


class SignatureError(ValueError):
    """``invalid`` — not a PNG; ``too_large`` — declares too many pixels;
    ``empty`` — nothing drawn on it."""


def _channel_is_white(band):
    return band.point(lambda v: 255 if v >= NEAR_WHITE else 0)


def prepare_signature(value) -> bytes:
    """The signature (a PNG, base64 or a data URL) with near-white made transparent,
    ready to stamp. Raises :class:`SignatureError`."""
    try:
        raw = base64.b64decode(str(value).split(",")[-1], validate=True)
    except Exception:  # noqa: BLE001 — anything undecodable is simply "not a signature"
        raise SignatureError("invalid") from None
    if raw[:8] != PNG_MAGIC or raw[12:16] != b"IHDR":
        raise SignatureError("invalid")
    width, height = int.from_bytes(raw[16:20], "big"), int.from_bytes(raw[20:24], "big")
    if width * height > MAX_DECODE_PIXELS:
        raise SignatureError("too_large")
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except Exception:  # noqa: BLE001
        raise SignatureError("invalid") from None

    img = img.convert("RGBA")
    if width * height > MAX_SIGNATURE_PIXELS:
        scale = math.sqrt(MAX_SIGNATURE_PIXELS / (width * height))
        img = img.resize((max(1, int(width * scale)), max(1, int(height * scale))))
    r, g, b, alpha = img.split()
    white = ImageChops.multiply(ImageChops.multiply(_channel_is_white(r), _channel_is_white(g)),
                                _channel_is_white(b))
    alpha = ImageChops.multiply(alpha, ImageChops.invert(white))  # white or clear -> 0
    if alpha.getbbox() is None:
        raise SignatureError("empty")
    img.putalpha(alpha)
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()
