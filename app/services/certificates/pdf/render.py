"""Fill a course's certificate template — the ``ai-asia-contract`` certificate logic.

One function serves every programme's template (AI Engineer, AI for Leaders,
Corporate Leaders, Junior AI 10-13 / 14-18 …) because they share placeholders:

``#certificate_no``  the certificate number, centred, body font
``#firstname #lastname``  the name in Latin letters, centred, name font, shrunk to fit
``#date``  the issue date (``October 9, 2026``), centred, bold italic
``#capstone_topic``  the final-project title after its label (left empty if none)
the sample QR (or ``#qr``)  a QR to the certificate's verification page

Each placeholder's text is deleted (the background shows through, as with the
earlier redaction) and the value is written at the placeholder's own size, colour
and baseline, so a re-exported template needs no code change.
"""
from __future__ import annotations

import functools
import io
import os
from datetime import date
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.errors import PyPdfError
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from app import pdftools

from . import qr
from .names import full_name, long_date

_FONTS = Path(pdftools.__file__).resolve().parent / "fonts"
INK = (0x3D / 255, 0x39 / 255, 0x39 / 255)  # the earlier certificates' dark grey
# (env override, bundled OFL font). The earlier AI Engineer name font (Liana) has no
# licence on record, so it is only used when CERT_NAME_FONT points at a licensed copy.
_FONT_FILES = {
    "name": ("CERT_NAME_FONT", "CormorantGaramond-Regular.ttf"),
    "body": ("CERT_BODY_FONT", "OpenSans-Regular.ttf"),
    "date": ("CERT_DATE_FONT", "OpenSans-BoldItalic.ttf"),
}
TOKENS = ("#certificate_no", "#firstname", "#lastname", "#date", "#capstone_topic", "#qr")


class TemplateError(Exception):
    """The template bytes are not a readable PDF."""


@functools.cache
def font(role: str) -> str:
    env, bundled = _FONT_FILES[role]
    path = os.environ.get(env) or str(_FONTS / bundled)
    name = f"Cert-{role}"
    pdfmetrics.registerFont(TTFont(name, path))
    return name


def _rgb(color):
    """The placeholder's fill colour as RGB, or the default ink."""
    values = color if isinstance(color, (list, tuple)) else (color,)
    try:
        values = [float(v) for v in values]
    except (TypeError, ValueError):
        return INK
    if len(values) == 1:
        return (values[0],) * 3
    if len(values) == 3:
        return tuple(values)
    if len(values) == 4:
        c, m, y, k = values
        return tuple((1 - v) * (1 - k) for v in (c, m, y))
    return INK


def _fit(face: str, text: str, size: float, max_width: float, floor: float) -> float:
    while size > floor and pdfmetrics.stringWidth(text, face, size) > max_width:
        size -= 0.5
    return size


def _write(c, face, text, hit, *, centre_x=None, max_width=None, floor_ratio=0.4):
    """``text`` on ``hit``'s baseline, in its size (shrunk to ``max_width``) and colour."""
    size = hit.size
    if max_width:
        size = _fit(face, text, size, max_width, size * floor_ratio)
    c.setFont(face, size)
    c.setFillColorRGB(*_rgb(hit.color))
    if centre_x is None:
        c.drawString(hit.x0, hit.baseline, text)
    else:
        c.drawCentredString(centre_x, hit.baseline, text)


def _painter(found, values, qr_box):
    def paint(c, width, _height):
        for hit in found["#certificate_no"]:
            _write(c, font("body"), values["number"], hit, centre_x=(hit.x0 + hit.x1) / 2)
        names = found["#firstname"] + found["#lastname"]
        if names:
            x0, _, x1, _ = pdftools.union(names)
            head = min(names, key=lambda h: (h.y0, h.x0))
            _write(c, font("name"), values["name"], head, centre_x=(x0 + x1) / 2,
                   max_width=max(x1 - x0, width * 0.62))
        for hit in found["#date"]:
            _write(c, font("date"), values["date"], hit, centre_x=(hit.x0 + hit.x1) / 2)
        for hit in found["#capstone_topic"]:
            if values["capstone"]:
                _write(c, font("body"), values["capstone"], hit,
                       max_width=width * 0.94 - hit.x0, floor_ratio=0.8)
        if qr_box is not None:
            qr.draw(c, qr_box, values["verify_url"])

    return paint


def fill_certificate(template: bytes, *, number: str, first_name: str | None,
                     last_name: str | None, issued_on: date, verify_url: str,
                     capstone: str = "", layouts=None) -> bytes:
    """``layouts`` — the template already read by :func:`app.pdftools.read_pages`
    (read-only, so one parse serves a whole class)."""
    try:
        writer = PdfWriter(clone_from=PdfReader(io.BytesIO(template)))
        layouts = layouts or pdftools.read_pages(template)
    except Exception as exc:  # noqa: BLE001 — pdfminer / pypdf raise many types
        raise TemplateError(str(exc)) from exc
    values = {"number": number, "name": full_name(first_name, last_name),
              "date": long_date(issued_on), "capstone": capstone, "verify_url": verify_url}

    for index, (page, layout) in enumerate(zip(writer.pages, layouts)):
        streams = pdftools.streams(layout)
        found = {t: pdftools.find(streams, t, ignore_spaces=True) for t in TOKENS}
        width, height = float(page.mediabox.width), float(page.mediabox.height)
        marker = found["#qr"][0] if found["#qr"] else None
        # Only the first page carries the sample QR of a one-page certificate.
        qr_box = qr.find_box(page, layout, width, height, marker) if index == 0 else None
        hits = [h for hits in found.values() for h in hits]
        if not hits and qr_box is None:
            continue
        pdftools.remove(page, streams, hits)
        pdftools.stamp(page, _painter(found, values, qr_box))

    out = io.BytesIO()
    try:
        writer.write(out)
    except PyPdfError as exc:
        raise TemplateError(str(exc)) from exc
    return out.getvalue()
